import sys
import pandas as pd
from db_config import db_config
from geedar_core.database import GeedarDB

try:
    geedar_db = GeedarDB(conn_dict=db_config["conn_dict"], db_names=db_config["db_names"])
    df = geedar_db.get_table("station")
    print(df.columns.tolist())
    df_demands = geedar_db.get_demands()
    print(df_demands.columns.tolist())
except Exception as e:
    print(e)
