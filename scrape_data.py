import requests
import js2py
from copy import copy
import re
import pandas as pd
from bs4 import BeautifulSoup as bs
import polyline_utils as plu
import sqlite3
from pathlib import Path

Path('seneca7_data.db').touch()
race_length = 77.7
main_data = requests.get("http://www.seneca7.com/results.html")
soup = bs(main_data.content, 'html.parser')
race_links = soup.find_all('a', {"href": True, "class": "icon solid fa-running"})
split_links = [r['href'].split("jsp?r=") for r in race_links]
race_ids = [r[1] for r in split_links if len(r)==2]
dist_conv = 6.213712E-4
years_to_add_bike_data = [2023,2022,2019,2018,2017,2016]
bike_bibs = { #most of this data is only in pdf files... had to be scraped by hand
             2023: [4,293,42,51,26,7,254,72,71,282,181,49,6,307,262,2,67,13,48,46,31,61,22,275],
             2022: [11,238,101,223,167,82,77,153,190,116,204,155,53,222,19,75,2,188,232,30,8],
             2019: [23,234,261,55,315,217,27,43,26,13,288,153,17,46,117,42,19,39,11,248,186],
             2018: [56,66,222,31,37,234,324,74,29,42,241,55,178,114,46,30,133,47,341,156,166,165,34,59,50,33,269,258],
             2017: [56,41,66,1,17,20,26,74,33,81,35,71,76,50,55,14,54,67,68,59,132,17,174,153,7,16,3,51],
             2016: [3,4,52,8,31,273,10,25,35,38,12,36,45,282,39,29,9,274,31,158,19,18,20,41]
            }

### Scrape data ###
def find_lines_with_word(text, word):
    lines = text.splitlines()
    matching_lines = [line for line in lines if word in line]
    return matching_lines

def get_race_info(race_id, url1, url2, scripts_list):
    vardata = requests.get(url1+i)
    soup = bs(vardata.content, 'html.parser')
    js_script = soup.find_all('script',src=None)[0].get_text()
    
    race_start_line = find_lines_with_word(js_script, "var raceStart =")
    categories_line = find_lines_with_word(js_script, "var categories =")
    waves_line = find_lines_with_word(js_script, "var waves =")
    info = [race_start_line,categories_line,waves_line]
    
    base_url = url2+i+'/'
    runners0_url = base_url+scripts_list[0]
    elapsed_url = base_url+scripts_list[1]
    paths_url = base_url+scripts_list[2]
    waypoints_url = base_url+scripts_list[3]
    
    ## Parse runner data ##
    r = requests.get(runners0_url)
    get_running_data = js2py.eval_js(js2py.eval_js(str(r.content)[1:]))
    runner0 = get_running_data().to_dict()
    
    ## Parse elapsed data ##
    r = requests.get(elapsed_url)
    get_elapsed_data = js2py.eval_js(js2py.eval_js(str(r.content)[1:]))
    elapsed = get_elapsed_data().to_dict()
    
    ## Parse waypoints data ##
    r = requests.get(waypoints_url)
    get_waypoints_data = js2py.eval_js(js2py.eval_js(str(r.content)[1:]))
    waypoints = get_waypoints_data().to_list()
    
    ## Parse paths data ##
    r = requests.get(paths_url)
    js_string = js2py.eval_js(str(r.content)[1:])
    paths = plu.get_encoding(js_string,'google.maps.geometry.encoding.decodePath("','")')
    polylines = []
    for p in paths:
        polylines.append(plu.decode_polyline(str(p)))

    year, month, day, hour, minute, second = plu.get_encoding(info[0][0],'Date(',');')[0].split(',')
    info[0] = [int(i) for i in [year, month, day, hour, minute, second]]
    try:
        info[1] = plu.get_encoding(info[1][0],'[',']')[0].split(',')
        info[1] = [i.replace('"','') for i in info[1]]
        info[2] = plu.get_encoding(info[2][0],'[',']')[0].split(',')
        info[2] = [int(i) for i in info[2]]
    except:
        pass
    return([info, runner0, elapsed, waypoints, polylines])    

#iterate through years
all_data = {}
for i in race_ids:
    try:
        info, runner0, elapsed, waypoints, polylines = get_race_info(i, "https://live.resport.io/splits.jsp?r=", 
                                                                    'https://storage.googleapis.com/retracker.appspot.com/races/', 
                                                                    ['runners0.js','elapsed.js','paths.js','waypoints.js'])    

        all_data[info[0][0]] = {'meta': info, 'runners': runner0, 'times': elapsed, 'waypoints': waypoints, 'paths': polylines}
#        print(list(elapsed.items())[0])

    except:    
        try:
            info, runner0, elapsed, waypoints, polylines = get_race_info(i, "http://track.seneca7.com/results.jsp?r=", 
                                                                        'https://storage.googleapis.com/tracker-1144.appspot.com/races/', 
                                                                        ['runners.js','times.js','paths.js','waypoints.js'])

            all_data[info[0][0]] = {'meta': info, 'runners': runner0, 'times': elapsed, 'waypoints': waypoints, 'paths':polylines}
#            print(list(elapsed.items())[0]) 
        except:
            continue
######

### Clean data ###
years = list(all_data.keys())
for y in years:
    for i in all_data[y]['runners'].values():
        i['y'] = y #add year as column
        try:
            i['c'] = all_data[y]['meta'][1][i['c']]
            i['w'] = all_data[y]['meta'][2][i['w']]
        except:
            pass
        i['n'] = i['n'].replace("â\x80\x99", "\'") #fix strings
        if 'p' in i:
            i['p'] = i.pop('p') #redundant data that's formatted inconsistently across years
        if 's' in i:
            i['w'] = i.pop('s')
        try:
            del i['g'] #remove uniform and some redundant fields
        except KeyError:
            pass
        try:
            del i['e']
        except KeyError:
            pass
        try:
            del i['f']
        except KeyError:
            pass
        if y in years_to_add_bike_data and i['b'] in bike_bibs[y]: #did the team bike to waypoints?
            i['bike'] = 'y'
        else:
            i['bike'] = 'n'

runner_data = {}
time_data = {}
waypoints = {}
paths = {}
t_data = {}
c_data = {}
p_data = {}
for y in years:
    shared_keys = set(all_data[y]['runners']).intersection(runner_data)
    if shared_keys == set():
        runner_data.update(all_data[y]['runners']) #add all runner data through the years to one table
    else:
        print("Error: colliding runner keys")
        print(shared_keys)
        break
    shared_keys = set(all_data[y]['times']).intersection(time_data)
    if shared_keys == set():
        time_data.update(all_data[y]['times']) #all time data in one table
    else:
        print("Error: colliding time keys")
        print(shared_keys)
        break

    year_wp = all_data[y]['waypoints'] #all waypoints in one table
    for wp in year_wp:
        wp['year'] = y
        curr_id = wp['id']
        del wp['id']
        waypoints[curr_id] = wp
    paths[y] = all_data[y]['paths']

path_data = [] #format path coordinate data for table form
for y in years:
    curr_path_data = paths[y]
    for i,path in enumerate(curr_path_data):
        for j,coord in enumerate(path):
            path_data.append([y,i,j,coord[0],coord[1]])

paths_df = pd.DataFrame(path_data, columns=['year','path','waypoint','lat','lon'])

for i in time_data: #different tables for times, pace, and speed
    tlist = {}
    clist = {}
    plist = {}
    for k,j in enumerate(time_data[i]):
        tlist["c"+str(k)] = j['t']
        clist["c"+str(k)] = j['c']
        plist["c"+str(k)] = j['p']
    t_data[i] = tlist
    c_data[i] = clist
    p_data[i] = plist

t_df = pd.DataFrame(t_data).T
c_df = pd.DataFrame(c_data).T
p_df = pd.DataFrame(p_data).T
p_df['c0'] = float('nan') #pace and time at start are not defined
c_df['c0'] = float('nan') 
c_df['overall'] = (t_df['c21']-t_df['c0'])/60/race_length #compute pace for whole race 
p_df = c_df.map(lambda x: 60/(x+1E-8)) #recompute speed for consistency with pace
filter_cond = c_df.iloc[:,1:].min(axis=1) < 3.75 #filter out incorrect entries... nobody in this race broke the world record mile time
bad_ids = p_df[filter_cond].index.to_list()

runner_df = pd.DataFrame(runner_data).T
runner_df.drop('p', axis=1, inplace=True)
runner_df['place'] = float('nan')
waypoint_df = pd.DataFrame(waypoints).T

runner_df.drop(bad_ids, inplace=True)
t_df.drop(bad_ids, inplace=True)
c_df.drop(bad_ids, inplace=True)
p_df.drop(bad_ids, inplace=True)

runner_df.rename(columns={'Unnamed: 0': 'index', 'b': 'bib_number', 'c': 'category', 'n': 'team_name', 'w': 'start_time', 'y': 'year', 'bike': 'bikers'}, inplace=True)
runner_df['category'] = runner_df['category'].str.lower().replace("open","men",regex=True).replace("team","",regex=True).replace("solo","",regex=True)
t_df.rename(columns={'Unnamed: 0': 'index'}, inplace=True)
c_df.rename(columns={'Unnamed: 0': 'index'}, inplace=True)
p_df.rename(columns={'Unnamed: 0': 'index'}, inplace=True)
waypoint_df.rename(columns={'Unnamed: 0': 'index'}, inplace=True)
######

### Compute Placements ###
grouped_data = runner_df.groupby(["year","category"])
grouped_ids = []
for name, group in grouped_data:
    grouped_ids.append(group.index)

team_place = {}
for g in grouped_ids:
    tot_times = t_df['c21'][g] - t_df['c0'][g]
    sorted_times = sorted(tot_times.keys(), key=lambda k: tot_times[k])
    placements = {k: p for p,k in enumerate(sorted_times)}
    for ids,place in placements.items():
        team_place[ids] = place + 1

runner_df['place'] = runner_df.index.map(team_place)
######

### Write to SQLite Database ###
conn = sqlite3.connect('seneca7_data.db')
c = conn.cursor()

c.execute("CREATE TABLE runners (team_id int, bib_number int, category text, team_name text, place int, start_time int, year int, bikers text)")
runner_df.to_sql('runners', conn, if_exists='append', index=True, index_label='team_id')

c.execute("CREATE TABLE time (team_id int, c0 float, c1 float, c2 float, c3 float, c4 float, c5 float, c6 float, c7 float, c8 float, c9 float, c10 float, c11 float, c12 float, c13 float, c14 float, c15 float, c16 float, c17 float, c18 float, c19 float, c20 float, c21 float)")
t_df.to_sql('time', conn, if_exists='append', index=True, index_label='team_id')
c.execute("CREATE TABLE pace (team_id int, c0 float, c1 float, c2 float, c3 float, c4 float, c5 float, c6 float, c7 float, c8 float, c9 float, c10 float, c11 float, c12 float, c13 float, c14 float, c15 float, c16 float, c17 float, c18 float, c19 float, c20 float, c21 float, overall float)")
c_df.to_sql('pace', conn, if_exists='append', index=True, index_label='team_id')
c.execute("CREATE TABLE speed (team_id int, c0 float, c1 float, c2 float, c3 float, c4 float, c5 float, c6 float, c7 float, c8 float, c9 float, c10 float, c11 float, c12 float, c13 float, c14 float, c15 float, c16 float, c17 float, c18 float, c19 float, c20 float, c21 float, overall float)")
p_df.to_sql('speed', conn, if_exists='append', index=True, index_label='team_id')

waypoint_df.drop('color', axis=1, inplace=True)
c.execute("CREATE TABLE waypoints (id int, distance float, label text, lat float, lon float, name text, year int)")
waypoint_df.to_sql('waypoints', conn, if_exists='append', index=True, index_label='id')

c.execute("CREATE TABLE paths (year int, path int, waypoint int, lat float, lon float)")
paths_df.to_sql('paths', conn, if_exists='append', index=False)
######
