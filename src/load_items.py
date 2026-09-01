import pandas as pd
import sqlite3
import os

Base=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
csv_path=os.path.join(Base,"data","items.csv")
db_path=os.path.join(Base,"data","bakery_shop.db")

def load():
    df=pd.read_csv(csv_path)
    con=sqlite3.connect(db_path)
    df.to_sql("items",con,if_exists="replace",index=False)
    con.commit()
    count=con.execute("select count(*) from items").fetchone()[0]
    con.close()
    print(f"loaded {count} items into {db_path}")

if __name__=="__main__":
    load()