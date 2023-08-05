import argparse
import glob
import numpy as np
import pandas as pd
import lightgbm as lgb
from ashrae.utils import (
    MODEL_PATH, OUTPUT_PATH, Logger, timer, 
    rmsle, load_data,
)

parser = argparse.ArgumentParser(description="")

parser.add_argument("--normalize_target", action="store_true", 
    help="If True then normalize the meter_reading by dividing by log1p(square_feet).")


FEATURES = [
    # building meta features
    "square_feet", "year_built", "floor_count",

    # cat cols
    "building_id", "meter", "primary_use", 
    "hour", "weekday", "weekday_hour",
    "building_weekday_hour", "building_weekday",
    "building_hour", 

    # raw weather features
    "air_temperature", "cloud_coverage", "dew_temperature",
    "precip_depth_1_hr", "sea_level_pressure", "wind_direction", "wind_speed",

    # derivative weather features
    "air_temperature_mean_lag7", "air_temperature_std_lag7",
    "air_temperature_mean_lag73", "air_temperature_std_lag73",

    # time features
    "weekday_x", "weekday_y", "is_holiday",

    # target encoding features
    "gte_meter_building_id_hour", "gte_meter_building_id_weekday",
]

CAT_COLS = [
    "building_id", "meter", "primary_use", 
    "hour", "weekday", "weekday_hour",
    "building_weekday_hour", "building_weekday",
    "building_hour", 
]

DROP_COLS = [
    # time columns
    "year", "timestamp", "hour_x", "hour_y", 

    # weather extremum
    "air_temperature_min_lag7", "air_temperature_max_lag7",
    "air_temperature_min_lag73", "air_temperature_max_lag73",    

    # first-order gte
    "gte_hour", "gte_weekday", "gte_month", "gte_building_id",
    "gte_meter", "gte_meter_hour", "gte_primary_use", "gte_site_id", 

    # second-order gte
    "gte_meter_weekday", "gte_meter_month", "gte_meter_building_id",
    "gte_meter_primary_use", "gte_meter_site_id",  

    # month columns
    "month_x", "month_y", "building_month", #"month", 
    "gte_meter_building_id_month"
]


if __name__ == "__main__":
    """
    python scripts/04_predict_lgb_site.py --normalize_target
    python scripts/04_predict_lgb_site.py    
    """

    args = parser.parse_args()

    with timer("Loading data"):
        test = load_data("test_clean")
        test.drop(DROP_COLS, axis=1, inplace=True)

    with timer("Preprocesing"):
        for x in CAT_COLS:
            test[x] = test[x].astype("category")

        if args.normalize_target:
            target_encode_cols = [x for x in test.columns if "gte" in x]
            test[target_encode_cols] = test[target_encode_cols]/np.log1p(test[["square_feet"]].values)

    with timer("Predicting"):        
        # get base file name
        test_preds = np.zeros(len(test))
        for s in range(16):    

            # create sub model path
            if args.normalize_target:
                sub_model_path = f"{MODEL_PATH}/lgb-split_site/target_normalization/site_{s}"
            else:
                sub_model_path = f"{MODEL_PATH}/lgb-split_site/no_normalization/site_{s}"

            # remove indices not in this site
            X = test.loc[test.site_id == s, FEATURES]
            print(f"split site {s}: test size {len(X)}")

            # load models
            model_list = [
                lgb.Booster(model_file=model_name)
                for model_name in glob.glob(f"{sub_model_path}/*")
            ]

            # predict
            msg = f'Predicting for site {s} - models# {len(model_list)}, test# {len(X)}'
            with timer(msg):
                assert model_list, "No models to load"
                if len(model_list) == 1:
                    preds = model_list[0].predict(X)
                else:
                    preds = np.mean([model.predict(X) for model in model_list], 0)
                test_preds[test.site_id == s] = preds

        # invert target transformation    
        if args.normalize_target:
            test_preds *= np.log1p(test.square_feet)

        test_preds = np.expm1(test_preds)

        # correct site 0
        test_preds[(test.site_id == 0) & (test.meter == 0)] *= 3.4118
        test_preds[test_preds < 0 ] = 0

    # save data
    if args.normalize_target:
        np.save(f"{OUTPUT_PATH}/lgb-split_site-target_normalization", test_preds)
    else:
        np.save(f"{OUTPUT_PATH}/lgb-split_site-no_normalization", test_preds)            