import xarray as xr
from pathlib import Path
import numpy as np
import yaml
import datetime as dt
import cdsapi


### Set up and parameter selection ########

# set up paths
this_dir = Path(__file__).parent
data_dir = this_dir / "years"
tmp_data_dir = this_dir / "tmp_data"
data_dir.mkdir(parents=True, exist_ok=True)  # make dir if it doesn't exist
tmp_data_dir.mkdir(parents=True, exist_ok=True)  # make dir if it doesn't exist

# read configuration
config_path = this_dir / "config.yaml"
with open(config_path, "r") as file:
    config = yaml.safe_load(file)

start_date = dt.datetime.strptime(config["start_date"] + "-01", "%Y-%m-%d")
end_date = dt.datetime.strptime(config["end_date"] + "-01", "%Y-%m-%d")
timestep_in_hours = config["timestep_in_hours"]
download_hours = np.arange(0, 24, timestep_in_hours)
download_hours_str = [f"{str(hour).zfill(2)}:00" for hour in download_hours]
download_days_by_month_by_year = {}
current_date = start_date
while current_date < end_date:
    year = current_date.year
    month = current_date.month
    if year not in download_days_by_month_by_year:
        download_days_by_month_by_year[year] = {}
    if month not in download_days_by_month_by_year[year]:
        download_days_by_month_by_year[year][month] = set()
    download_days_by_month_by_year[year][month].add(current_date.day)
    current_date += dt.timedelta(days=1)

years = sorted(download_days_by_month_by_year.keys())
print(f"Downloading OLR data for years: {years}")

dataset = "reanalysis-era5-single-levels"
client = cdsapi.Client()

for y, year in enumerate(years):
    ds_list = []  # collect datasets to concatenate later

    for m, month in enumerate(sorted(download_days_by_month_by_year[year].keys())):
        days = sorted(download_days_by_month_by_year[year][month])

        request = {
            "product_type": ["reanalysis"],
            "variable": ["top_net_thermal_radiation"],
            "year": [str(year)],
            "month": [str(month).zfill(2)],
            "day": [str(day).zfill(2) for day in days],
            "time": download_hours_str,
            "area": [90, -80, -90, 80],
            "data_format": "netcdf",
            "download_format": "unarchived",
        }

        tmp_path = this_dir / "tmp_data" / f"{year}_{str(month).zfill(2)}.nc"
        if tmp_path.exists():
            tmp_path.unlink()  # remove existing olr file

        client.retrieve(dataset, request).download(
            tmp_path
        )  # download the data to disk
        ds = (
            xr.open_dataset(tmp_path).squeeze().load()
        )  # load the data into memory eagerly
        ds_list.append(ds)

        tmp_path.unlink()  # remove the tmp file after download

    # concatenate all months for the year# concatenate the datasets along the time dimension
    ds = xr.concat(ds_list, dim="valid_time")
    # convert to W/m^2, since it's a one-hour accumulation and signed opposite of OLR
    # per https://confluence.ecmwf.int/pages/viewpage.action?pageId=82870405#heading-Meanratesfluxesandaccumulations
    ds["VAR_OLR"] = -ds["ttr"] / 3600  # https://codes.ecmwf.int/grib/param-db/179
    ds = ds["VAR_OLR"]  # remove all other variables
    if config["daily_mean"]:
        ds = ds.resample(valid_time="1D").mean()  # compute daily means
        save_path = data_dir / f"{year}_daily_mean.nc"
    else:
        save_path = data_dir / f"{year}.nc"

    ds.to_netcdf(
        save_path, mode="w", format="NETCDF4", engine="netcdf4"
    )  # save to disk
    print(f"Saved OLR data to {save_path}.")
