import io
import logging
from datetime import timedelta

import pandas as pd
import requests
from django.conf import settings
from django.contrib.gis.gdal import DataSource as DataSource
from django.contrib.gis.geos import GEOSGeometry, Point

from eco_counter.models import (
    ECO_COUNTER,
    Station,
    TRAFFIC_COUNTER,
    TRAFFIC_COUNTER_END_YEAR,
    TRAFFIC_COUNTER_START_YEAR,
)
from eco_counter.tests.test_import_counter_data import TRAFFIC_COUNTER_TEST_COLUMNS
from mobility_data.importers.utils import get_root_dir

logger = logging.getLogger("eco_counter")

TRAFFIC_COUNTER_METADATA_GEOJSON = "traffic_counter_metadata.geojson"


# Create a dict where the years to be importer are keys and the value is the url of the csv data.
# e.g. {2015, "https://data.turku.fi/2yxpk2imqi2mzxpa6e6knq/2015_laskenta.csv"}
keys = [k for k in range(TRAFFIC_COUNTER_START_YEAR, TRAFFIC_COUNTER_END_YEAR + 1)]
TRAFFIC_COUNTER_CSV_URLS = dict(
    [
        (k, f"{settings.TRAFFIC_COUNTER_OBSERVATIONS_BASE_URL}{k}_laskenta.csv")
        for k in keys
    ]
)


def get_traffic_counter_metadata_data_layer():
    meta_file = f"{get_root_dir()}/eco_counter/data/{TRAFFIC_COUNTER_METADATA_GEOJSON}"
    return DataSource(meta_file)[0]


def get_dataframe(url):
    response = requests.get(url)
    assert (
        response.status_code == 200
    ), "Fetching observations csv {} status code: {}".format(url, response.status_code)
    string_data = response.content
    csv_data = pd.read_csv(io.StringIO(string_data.decode("utf-8")))
    return csv_data


def get_eco_counter_csv():
    return get_dataframe(settings.ECO_COUNTER_OBSERVATIONS_URL)


def get_traffic_counter_test_dataframe():
    """
    Generate a Dataframe with only column names for testing. The dataframe
    will then be populated with generated values. The reason for this is
    to avoid calling the very slow get_traffic_counter_csv function to only
    get the column names which is needed for generating testing data.
    """
    return pd.DataFrame(columns=TRAFFIC_COUNTER_TEST_COLUMNS)


def get_traffic_counter_csv(start_year=2015):
    df = get_dataframe(TRAFFIC_COUNTER_CSV_URLS[start_year])
    # Concat the Traffic counter CSV data into one CSV.
    for key in TRAFFIC_COUNTER_CSV_URLS.keys():
        # Skip start year as it is in the initial dataframe, skip also
        # data from years before the start year.
        if key <= start_year:
            continue
        app_df = get_dataframe(TRAFFIC_COUNTER_CSV_URLS[key])
        # ignore_index=True, do not use the index values along the concatenation axis.
        # The resulting axis will be labeled 0, …, n - 1.
        df = pd.concat([df, app_df], ignore_index=True)

    data_layer = get_traffic_counter_metadata_data_layer()

    ids_not_found = 0
    # Rename columns using the metadata to format: name_type|direction
    # e.g. Yliopistonkatu AK
    for feature in data_layer:
        id = feature["Mittauspisteiden_ID"].as_int()
        direction = feature["Suunta"].as_string()
        # TODO, remove when the final/corrected version of the metadata is available
        direction = "K"
        measurement_type = feature["Tyyppi"].as_string()
        # with the id find the column from the data csv
        name = feature["Osoite_fi"].as_string()
        regex = rf".*\({id}\)"
        column = df.filter(regex=regex)
        if len(column.keys()) > 1:
            logger.error(f"Multiple ids: {id}, found in csv data, skipping.")
            continue
        if len(column.keys()) == 0:
            logger.warning(f"ID:{id} in metadata not found in csv data")
            ids_not_found += 1
            continue
        col_name = column.keys()[0]
        new_name = f"{name} {measurement_type}{direction}"
        # Rename the column with the new name that is built from the metadata.
        df.columns = df.columns.str.replace(col_name, new_name, regex=False)
    # drop columns with number, i.e. not in metadata as the new column
    # names are in format name_type|direction and does not contain numbers
    df = df.drop(df.filter(regex="[0-9]+").columns, axis=1)
    # Combine columns with same name, i.e. combines lanes into one.
    # axis=1, split along columns.
    df = df.groupby(df.columns, axis=1).sum()
    logger.info(df.info(verbose=False))
    # Move column 'startTime to first (0) position.
    df.insert(0, "startTime", df.pop("startTime"))
    return df


def save_traffic_counter_stations():
    """
    Saves the stations defined in the metadata to Station table.
    """
    saved = 0
    data_layer = get_traffic_counter_metadata_data_layer()
    for feature in data_layer:
        name = feature["Osoite_fi"].as_string()
        name_sv = feature["Osoite_sv"].as_string()
        name_en = feature["Osoite_en"].as_string()
        if Station.objects.filter(name=name).exists():
            continue
        station = Station()
        station.name = name
        station.name_sv = name_sv
        station.name_en = name_en
        station.csv_data_source = TRAFFIC_COUNTER
        geom = GEOSGeometry(feature.geom.wkt, srid=feature.geom.srid)
        geom.transform(settings.DEFAULT_SRID)
        station.geom = geom
        station.save()
        saved += 1
    logger.info(f"Saved {saved} traffic-counter stations.")


def save_eco_counter_stations():
    response = requests.get(settings.ECO_COUNTER_STATIONS_URL)
    assert (
        response.status_code == 200
    ), "Fetching stations from {} , status code {}".format(
        settings.ECO_COUNTER_STATIONS_URL, response.status_code
    )
    response_json = response.json()
    features = response_json["features"]
    saved = 0
    for feature in features:
        station = Station()
        name = feature["properties"]["Nimi"]
        if not Station.objects.filter(name=name).exists():
            station.name = name
            station.csv_data_source = ECO_COUNTER
            lon = feature["geometry"]["coordinates"][0]
            lat = feature["geometry"]["coordinates"][1]
            point = Point(lon, lat, srid=4326)
            point.transform(settings.DEFAULT_SRID)
            station.geom = point
            station.save()
            saved += 1
    logger.info(
        "Retrieved {numloc} eco-counter stations, saved {saved} stations.".format(
            numloc=len(features), saved=saved
        )
    )


def gen_eco_counter_test_csv(keys, start_time, end_time):
    """
    Generates testdata for a given timespan,
    for every 15min the value 1 is set.
    """
    df = pd.DataFrame(columns=keys)
    df.keys = keys
    cur_time = start_time
    c = 0
    while cur_time <= end_time:
        # Add value to all keys(sensor stations)
        vals = [1 for x in range(len(keys) - 1)]
        vals.insert(0, str(cur_time))
        df.loc[c] = vals
        cur_time = cur_time + timedelta(minutes=15)
        c += 1
    return df
