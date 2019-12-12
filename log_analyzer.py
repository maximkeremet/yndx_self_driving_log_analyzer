import requests
import ast
import time
import pandas as pd
from datetime import datetime
import json

import geopandas as gpd
from shapely.geometry import Polygon
from geopy.distance import distance

import folium
from folium import plugins

import logging
from typing import Union, Dict, List, Tuple
from config import LOG_FILES_PATH, MONITORING_PATH, POLYGONS_PATH, RESULTS_PATH, LOCATION


class LogFileParser:
    def __init__(self,
                 url: str,
                 monitor: logging.Logger):
        self.url = url
        self.monitor = monitor
        self.log_file_path = LOG_FILES_PATH
        self.monitoring_path = MONITORING_PATH

    def download_file(self):
        """
        Downloads file and writes in a directory with log files.
        Constructs a file name as `log_file_{date}_{unix_ts}.txt'


        :return: full path where file is located with its name
        """

        self.monitor.info(f'-> Started to download log file from: {self.url}...')
        try:
            log_file = requests.get(self.url, allow_redirects=True)

            postfix = f'{datetime.today().strftime("%Y_%m_%d")}_{str(int(time.time()))}'
            filename = f"log_file_{postfix}.txt"

            self.monitor.info(f'-> Writing file to {LOG_FILES_PATH}...')
            open(LOG_FILES_PATH + '/' + filename, 'wb').write(log_file.content)
            self.monitor.info(f'-> Finished writing file to {LOG_FILES_PATH}.')

            file_path = self.log_file_path + '/' + filename

            return file_path, postfix

        except requests.exceptions.SSLError as connection_error:
            self.monitor.exception(f'-> Something bad happened. Details:\n {repr(connection_error)}')
            return None, None

    def preprocess_log(self, log_file_full_path: str) -> Union[Dict, None]:
        """
        A function for parsing raw file. Splits log file by instances (geo coordinates lines and switcher binary target).
        Stores data in dictionaries, unions 2 dicts and sorts by ts to create proper sequence in time.

        :return: a dict with log file data sorted by ts
        """

        try:
            with open(log_file_full_path, 'r') as log_file:

                switcher, coords = {}, {}

                self.monitor.info('-> Started to parse log file...')
                for line in log_file:
                    try:
                        if 'control_switch_on' in line:
                            switch, ts = json.loads(line).values()
                            switcher[ts] = int(switch)
                        elif 'geo' in line:
                            geo, ts = json.loads(line).values()
                            coords[ts] = geo
                        else:
                            self.monitor.warning('-> Unknown happened on line while parsing:\n', line)
                            continue
                    except Exception as e:
                        self.monitor.exception(" Something bad happened", repr(e))
                self.monitor.info(f'-> Parsed log with {len(switcher)} switcher marks and {len(coords)} coords.')
                log_file.close()

                merged_log = {**switcher, **coords}
                sequence = {key: merged_log[key] for key in sorted(merged_log.keys())}
                self.monitor.info(f' -> Merged signal types and sorted by ts. Got a sequenced log with {len(sequence)} records.')

            return sequence

        except Exception as e:
            self.monitor.exception(f'-> Something bad happened. Details:\n {repr(e)}')

            return None

    def parse_log(self):

        log_file_full_path, postfix = self.download_file()
        parsed_log = self.preprocess_log(log_file_full_path=log_file_full_path)

        return parsed_log, postfix


class LogFileCalculator(LogFileParser):

    def __init__(self, url: str, monitor: logging.Logger, parsed_log: Dict):
        super().__init__(url, monitor)
        self.parsed_log = parsed_log

    @staticmethod
    def convert_time(ts: int) -> str:
        converted_ts = datetime.utcfromtimestamp(ts // 10 ** 9)
        converted_ts = converted_ts.strftime('%Y-%m-%d %H:%M:%S')
        return converted_ts

    @staticmethod
    def validate_coordinates(coordinates: Dict) -> bool:
        if (coordinates['lat'] or coordinates['lon']) == 0.0:
            return False
        else:
            return True

    @staticmethod
    def check_switcher_state(line_state: str, current_state: str) -> str:
        if current_state != line_state:
            current_state = line_state
        else:
            pass
        return current_state

    @staticmethod
    def calculate_distance(current_geo_point: List, previous_geo_point: List) -> float:
        return round(distance(current_geo_point, previous_geo_point).m, 5)

    @staticmethod
    def generate_report(calculated_distances: Dict) -> pd.DataFrame:
        return pd.DataFrame(calculated_distances.items(), columns=['mode', 'distance, m'])

    def get_placeholder_values(self, preprocessed_log: Dict) -> List:
        """
        :param preprocessed_log: log file sorted by ts
        :return: initial values for control_switch_on and geo coords
        """

        start_state = {'start_switcher': None, 'start_coords': None}

        for placeholder in start_state.keys():
            for key, line in preprocessed_log.items():
                while start_state[placeholder] is None:
                    try:
                        if isinstance(line, Dict) and start_state['start_coords'] is None:  # ?
                            start_state['start_coords'] = list(line.values())
                        elif isinstance(line, int) and start_state['start_switcher'] is None:  # ?
                            start_state['start_switcher'] = line
                        break
                    except Exception as e:
                        self.monitor.exception(f'-> Something bad happened. Details:\n {repr(e)}')
        switcher_str = 'autopilot driving' if start_state['start_switcher'] else '`human driving`'
        self.monitor.info(f" -> Set {switcher_str} as start switcher mode and starting geo coordinates: "
                          f"lat: {start_state['start_coords'][0]}, long: {start_state['start_coords'][1]}.")

        return list(start_state.values())

    def process_log(self, log: Dict, placeholder_switcher: int, placeholder_geo: List) -> Dict:

        line_cnt = 0
        distance_counter = {'human': 0, 'autopilot': 0}  # human is 0, autopilot is 1 (checked )

        start = time.monotonic()

        for ts, event in log.items():
            line_cnt += 1

            current_switcher_str = 'autopilot' if placeholder_switcher else 'human'
            converted_ts = self.convert_time(ts)

            if isinstance(event, Dict):

                if self.validate_coordinates(event):
                    # if line contains geo coordinates - calculate distance and update values in dict
                    driven_distance = self.calculate_distance(placeholder_geo, list(event.values()))
                    distance_counter[current_switcher_str] += driven_distance

                    # update current geo position
                    placeholder_geo = event.values()

                    logging.info(f"{line_cnt}|{converted_ts}|{current_switcher_str}|"
                                 f"{driven_distance}|{distance_counter}|{list(placeholder_geo)}|{list(event.values())}")

            elif isinstance(event, int):

                placeholder_switcher = self.check_switcher_state(event, placeholder_switcher)

                logging.info(f"{line_cnt}|{converted_ts}|{current_switcher_str}|"
                             f"{driven_distance}|{distance_counter}|{list(placeholder_geo)}|{event}")
            else:
                pass
                self.monitor.warning(f'Something went wrong on line {line_cnt}')

        end = time.monotonic()
        self.monitor.info(" Total time spent on calculating report: {}".format("%6.2f" % (end - start)))

        return distance_counter

    def run_calculation(self) -> pd.DataFrame:

        initial_switcher, initial_geo_coords = self.get_placeholder_values(self.parsed_log)

        calculated_distances = self.process_log(log=self.parsed_log,
                                                placeholder_switcher=initial_switcher,
                                                placeholder_geo=initial_geo_coords)

        distance_report = self.generate_report(calculated_distances)

        self.monitor.info(distance_report)

        return distance_report


class DrawMap():

    def __init__(self, monitor: logging.Logger, parsed_log: Dict, postfix: str):
        self.monitor = monitor
        self.location = LOCATION
        self.result_path = RESULTS_PATH
        self.polygon_path = POLYGONS_PATH
        self.postfix = postfix
        self.parsed_log = parsed_log

    def get_car_route(self) -> pd.DataFrame:

        parsed_coords = []
        for k, v in self.parsed_log.items():
            try:
                if 'lat' in v.keys():
                    parsed_coords.append(list(v.values()))
            except Exception as e:
                continue

        df = pd.DataFrame(parsed_coords, columns=['lat', 'long'])

        self.monitor.info("-> Parsed car route.")
        return df

    def get_polygon_coordinates(self) -> Tuple[List, List]:
        polygon_query = f"https://nominatim.openstreetmap.org/" \
                        f"search?city={self.location.replace(' ', '+')}&polygon_geojson=1&format=json"
        r = requests.get(polygon_query)
        js = ast.literal_eval(r.text)

        self.monitor.info("-> Downloaded area polygon data points.")
        clean_polygon_coords = js[0]['geojson']['coordinates'][0]

        polygon_lats = [float(i[1]) for i in clean_polygon_coords]
        polygon_longs = [float(i[0]) for i in clean_polygon_coords]

        self.monitor.info("-> Created lat/long vectors.")
        return polygon_lats, polygon_longs

    def construct_polygon(self, polygon_longs: List, polygon_lats: List) -> gpd.GeoDataFrame:
        polygon_geom = Polygon(zip(polygon_longs, polygon_lats))

        crs = {'init': 'epsg:4326'}
        polygon = gpd.GeoDataFrame(index=[0], crs=crs, geometry=[polygon_geom])

        polygon.to_file(filename=f'{self.polygon_path}/polygon_{self.postfix}.geojson', driver='GeoJSON')
        polygon.to_file(filename=f'{self.polygon_path}/polygon_{self.postfix}.shp', driver="ESRI Shapefile")

        self.monitor.info("-> Created area polygon.")
        return polygon

    def plot_map(self, df, polygon, lat_col='latitude', lon_col='longitude', zoom_start=11,
                 plot_points=False, plot_polygon=False, pt_radius=1,
                 plot_heatmap=False, heat_map_weights_col=None,
                 heat_map_weights_normalize=True, heat_map_radius=10,
                 save=True, file_name='map.html'):
        """Creates a map given a dataframe of points. Can also produce a heatmap overlay

        Arg:
            df: dataframe containing points to maps
            lat_col: Column containing latitude (string)
            lon_col: Column containing longitude (string)
            zoom_start: Integer representing the initial zoom of the map
            plot_points: Add points to map (boolean)
            pt_radius: Size of each point
            draw_heatmap: Add heatmap to map (boolean)
            heat_map_weights_col: Column containing heatmap weights
            heat_map_weights_normalize: Normalize heatmap weights (boolean)
            heat_map_radius: Size of heatmap point

        Returns:
            folium map object
        """
        # center map in the middle of points center in
        middle_lat = df[lat_col].median()
        middle_lon = df[lon_col].median()

        curr_map = folium.Map(location=[middle_lat, middle_lon],
                              zoom_start=zoom_start)

        self.monitor.info("-> Drawing data points.")
        # add points to map
        if plot_points:
            for _, row in df.iterrows():
                folium.CircleMarker([row[lat_col], row[lon_col]],
                                    radius=pt_radius,
                                    fill_color="#3db7e4",  # divvy color
                                    ).add_to(curr_map)

        self.monitor.info("-> Drawing heatmap.")
        # add heatmap
        if plot_heatmap:
            # convert to (n, 2) or (n, 3) matrix format
            if heat_map_weights_col is None:
                cols_to_pull = [lat_col, lon_col]
            else:
                # if we have to normalize
                if heat_map_weights_normalize:
                    df[heat_map_weights_col] = \
                        df[heat_map_weights_col] / df[heat_map_weights_col].sum()

                cols_to_pull = [lat_col, lon_col, heat_map_weights_col]

            stations = df[cols_to_pull].values
            curr_map.add_child(plugins.HeatMap(stations, radius=heat_map_radius))

        if plot_polygon:
            self.monitor.info("-> Drawing city polygon area.")
            folium.GeoJson(polygon).add_to(curr_map)
        else:
            pass

        if save:
            self.monitor.info(f"-> Saving map to {self.result_path}.")
            curr_map.save(file_name)
            self.monitor.info(f"-> Saved.\n Script finished.")
        else:
            return curr_map

    def draw_map(self):

        polygon_lats, polygon_longs = self.get_polygon_coordinates()
        car_route = self.get_car_route()

        polygon = self.construct_polygon(polygon_lats, polygon_longs)

        map_path = f'{self.result_path}/map_{self.postfix}.html'

        self.plot_map(df=car_route,
                      polygon=polygon,
                      lat_col='lat',
                      lon_col='long',
                      plot_points=True,
                      plot_polygon=True,
                      plot_heatmap=True,
                      file_name=map_path)















