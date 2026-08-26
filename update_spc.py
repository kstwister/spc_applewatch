import io
import json
import zipfile
from datetime import datetime, timezone

import requests
import shapefile
from shapely.geometry import Point, shape


# Marlborough, Missouri
LATITUDE = 38.5709
LONGITUDE = -90.3375

#38.5709
#-90.3375

SPC_ZIP_URL = "https://www.spc.noaa.gov/products/outlook/day1otlk-shp.zip"


def get_value(record, fields):
    """Find the SPC risk value in a shapefile record."""
    data = dict(zip(fields, record))

    for key in ["LABEL", "LABEL2", "DN", "VALUE", "RISK"]:
        if key in data and data[key] not in (None, ""):
            return str(data[key]).strip()

    return None


def risk_for_file(zip_file, filename_part, point):
    """Return the risk polygon containing our location."""
    shp_name = None

    for name in zip_file.namelist():
        if filename_part in name.lower() and name.lower().endswith(".shp"):
            shp_name = name
            break

    if not shp_name:
        return None

    base = shp_name[:-4]

    shp = io.BytesIO(zip_file.read(base + ".shp"))
    shx = io.BytesIO(zip_file.read(base + ".shx"))
    dbf = io.BytesIO(zip_file.read(base + ".dbf"))

    reader = shapefile.Reader(shp=shp, shx=shx, dbf=dbf)

    fields = [field[0] for field in reader.fields[1:]]

    matches = []

    for sr in reader.iterShapeRecords():
        # SPC shapefiles can occasionally contain empty/null shapes.
        # Skip them instead of trying to convert them to GeoJSON.
        if sr.shape.shapeType == shapefile.NULL:
            continue
        polygon = shape(sr.shape.__geo_interface__)

        if polygon.contains(point) or polygon.touches(point):
            value = get_value(sr.record, fields)
            if value:
                matches.append(value)

    if not matches:
        return "0%"

    # Prefer the highest numerical percentage if multiple polygons overlap
    def numeric_value(value):
        try:
            return float(
                value.replace("%", "")
                .replace("SIGN", "")
                .replace("+", "")
            )
        except ValueError:
            return 0

    return max(matches, key=numeric_value)


def category_for_file(zip_file, point):
    shp_name = None

    for name in zip_file.namelist():
        if "_cat" in name.lower() and name.lower().endswith(".shp"):
            shp_name = name
            break

    if not shp_name:
        return "NONE"

    base = shp_name[:-4]

    shp = io.BytesIO(zip_file.read(base + ".shp"))
    shx = io.BytesIO(zip_file.read(base + ".shx"))
    dbf = io.BytesIO(zip_file.read(base + ".dbf"))

    reader = shapefile.Reader(shp=shp, shx=shx, dbf=dbf)
    fields = [field[0] for field in reader.fields[1:]]

    categories = []

    for sr in reader.iterShapeRecords():
        if sr.shape.shapeType == shapefile.NULL:
            continue
            
        polygon = shape(sr.shape.__geo_interface__)

        if polygon.contains(point) or polygon.touches(point):
            value = get_value(sr.record, fields)
            if value:
                categories.append(value.upper())

    if not categories:
        return "NONE"

    ranking = {
        "TSTM": 1,
        "MRGL": 2,
        "SLGT": 3,
        "ENH": 4,
        "MDT": 5,
        "HIGH": 6,
    }

    return max(categories, key=lambda x: ranking.get(x, 0))


def clean_percentage(value):
    if not value:
        return "0%"

    value = str(value).strip()

    # Already formatted as a percentage
    if "%" in value:
        return value
    try:
        number = float(value)
        if number == 0:
            return "0%"
        # SPC probabilities may be stored as decimals:
        # 0.02 = 2%, 0.05 = 5%, 0.10 = 10%, etc.
        if 0 < number < 1:
            number *= 100
        # Remove unnecessary decimal (.0)
        if number.is_integer():
            return f"{int(number)}%"
        return f"{number:g}%"
    except ValueError:
        return value


def main():
    print("Downloading latest SPC Day 1 outlook...")

    response = requests.get(SPC_ZIP_URL, timeout=30)
    response.raise_for_status()

    point = Point(LONGITUDE, LATITUDE)

    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        category = category_for_file(z, point)

        tornado = risk_for_file(z, "_torn", point)
        wind = risk_for_file(z, "_wind", point)
        hail = risk_for_file(z, "_hail", point)

    tornado_clean = clean_percentage(tornado)
    wind_clean = clean_percentage(wind)
    hail_clean = clean_percentage(hail)

    hazards = []

    if tornado_clean != "0%":
        hazards.append(f"🌪{tornado_clean}")

    if wind_clean != "0%":
        hazards.append(f"💨{wind_clean}")

    if hail_clean != "0%":
        hazards.append(f"🧊{hail_clean}")
    
    if category == "NONE":
        spc_summary = ""
    elif hazards:
        spc_summary = f"{category} | " + " ".join(hazards)
    else:
        spc_summary = category

    output = {
        "location": "Marlborough, MO",
        "⚡": spc_summary,
        "category": category,
        "tornado": tornado_clean,
        "wind": wind_clean,
        "hail": hail_clean,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }

    with open("spc.json", "w") as file:
        json.dump(output, file, indent=2)

    print("Updated spc.json:")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
