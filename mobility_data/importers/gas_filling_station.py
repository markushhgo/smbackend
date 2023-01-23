import logging

from django import db
from django.conf import settings
from django.contrib.gis.geos import Point, Polygon

from mobility_data.models import MobileUnit

from .constants import SOUTHWEST_FINLAND_BOUNDARY, SOUTHWEST_FINLAND_BOUNDARY_SRID
from .utils import (
    delete_mobile_units,
    fetch_json,
    get_or_create_content_type,
    get_street_name_and_number,
    get_street_name_translations,
    LANGUAGES,
    set_translated_field,
)

logger = logging.getLogger("mobility_data")
GAS_FILLING_STATIONS_URL = (
    "https://services1.arcgis.com/rhs5fjYxdOG1Et61/ArcGIS/rest/services/GasFillingStations/FeatureServer/0/query"
    "?f=json&where=1%3D1&outFields=OPERATOR%2CLAT%2CLON%2CSTATION_NAME%2CADDRESS%2CCITY%2CZIP_CODE%2CLNG_CNG%2CObjectId"
)

CONTENT_TYPE_NAME = "GasFillingStation"


class GasFillingStation:
    def __init__(self, elem, srid=settings.DEFAULT_SRID):
        # Contains the complete address with zip_code and city
        self.address = {}
        # Contains Only steet_name and number
        self.street_address = {}
        self.is_active = True
        attributes = elem.get("attributes")
        x = attributes.get("LON", 0)
        y = attributes.get("LAT", 0)
        self.point = Point(x, y, srid=srid)
        self.name = attributes.get("STATION_NAME", "")
        address_field = attributes.get("ADDRESS", "")
        street_name, street_number = get_street_name_and_number(address_field)
        self.zip_code = attributes.get("ZIP_CODE", "")
        self.city = attributes.get("CITY", "")
        translated_street_names = get_street_name_translations(street_name, self.city)
        for lang in LANGUAGES:
            if street_number:
                self.address[
                    lang
                ] = f"{translated_street_names[lang]} {street_number}, "
                self.address[lang] += f"{self.zip_code} {self.city}"
                self.street_address[
                    lang
                ] = f"{translated_street_names[lang]} {street_number}"
            else:
                self.address[lang] = f"{translated_street_names[lang]}, "
                self.address[lang] += f"{self.zip_code} {self.city}"
                self.street_address[lang] = f"{translated_street_names[lang]}"

            self.operator = attributes.get("OPERATOR", "")
        self.lng_cng = attributes.get("LNG_CNG", "")


def get_filtered_gas_filling_station_objects(json_data=None):
    """
    Returns a list of GasFillingStation objects that are filtered by location.
    Stations inside boundarys of Southwest Finland are included, the rest
    are discarded.
    """

    if not json_data:
        json_data = fetch_json(GAS_FILLING_STATIONS_URL)
    # srid = json_data["spatialReference"]["wkid"]
    # NOTE, hack to fix srid 102100 in source data causes "crs not found"
    srid = 4326
    # Create list of all GasFillingStation objects
    objects = [GasFillingStation(data, srid=srid) for data in json_data["features"]]
    # Filter objects by their location
    # Polygon used the detect if point intersects. i.e. is in the boundaries of SouthWest Finland.
    polygon = Polygon(SOUTHWEST_FINLAND_BOUNDARY, srid=SOUTHWEST_FINLAND_BOUNDARY_SRID)
    filtered_objects = [o for o in objects if polygon.intersects(o.point)]
    logger.info(
        "Filtered: {} gas filling stations by location to: {}.".format(
            len(json_data["features"]), len(filtered_objects)
        )
    )
    return filtered_objects


@db.transaction.atomic
def delete_gas_filling_stations():
    delete_mobile_units(CONTENT_TYPE_NAME)


@db.transaction.atomic
def create_gas_filling_station_content_type():
    description = "Gas filling stations in province of Southwest Finland."
    content_type, _ = get_or_create_content_type(CONTENT_TYPE_NAME, description)
    return content_type


@db.transaction.atomic
def save_to_database(objects, delete_tables=True):
    if delete_tables:
        delete_gas_filling_stations()

    content_type = create_gas_filling_station_content_type()
    for object in objects:
        is_active = object.is_active
        name = object.name
        extra = {}
        extra["operator"] = object.operator
        extra["lng_cng"] = object.lng_cng

        mobile_unit = MobileUnit.objects.create(
            is_active=is_active,
            name=name,
            geometry=object.point,
            extra=extra,
            content_type=content_type,
        )
        set_translated_field(mobile_unit, "address", object.address)
        mobile_unit.save()
    logger.info(f"Saved {len(objects)} gas filling stations to database.")
