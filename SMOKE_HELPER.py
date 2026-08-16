import json
import sqlite3
import sys


def main():
    cmd, db = sys.argv[1], sys.argv[2]
    con = sqlite3.connect(db)
    try:
        if cmd == "seed":
            con.execute("INSERT INTO prospects(company_name,contact_name,email,city,category,lead_score) VALUES(?,?,?,?,?,?)", ("Hotel Test Windows","Mme Test","test@example.invalid","Toulouse","hotels",95))
            con.execute("INSERT INTO prospects(company_name,phone,city,category,lead_score) VALUES(?,?,?,?,?)", ("Hotel SMS Test","0612345678","Toulouse","hotels",90))
            con.commit(); print("OK")
        elif cmd == "latest_campaign":
            row = con.execute("SELECT max(id) FROM campaigns").fetchone(); print(row[0] or "")
        elif cmd == "stats":
            cid = int(sys.argv[3])
            out = {
                "logs": con.execute("SELECT count(*) FROM communications WHERE campaign_id=?", (cid,)).fetchone()[0],
                "sim": con.execute("SELECT count(*) FROM communications WHERE campaign_id=? AND status='simulated'", (cid,)).fetchone()[0],
                "email": con.execute("SELECT count(*) FROM campaign_recipients WHERE campaign_id=? AND channel='email'", (cid,)).fetchone()[0],
                "sms": con.execute("SELECT count(*) FROM campaign_recipients WHERE campaign_id=? AND channel='sms'", (cid,)).fetchone()[0],
            }
            print(json.dumps(out))
        elif cmd == "logs":
            cid = int(sys.argv[3]); print(con.execute("SELECT count(*) FROM communications WHERE campaign_id=?", (cid,)).fetchone()[0])
        else:
            raise SystemExit("unknown command")
    finally:
        con.close()

if __name__ == "__main__":
    main()
