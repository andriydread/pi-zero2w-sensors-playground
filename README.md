## Environment Setup (On PiZero2W):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Mirror Workspace to PiZero:

`rsync -avz --delete --filter="merge .rsync-filter" . pi@pizero.local:~/air_test`

## .service file

sudo cp airmonitor.service /etc/systemd/system/

sudo nano /etc/systemd/system/airmonitor.service

sudo systemctl daemon-reload
sudo systemctl enable airmonitor.service
sudo systemctl start airmonitor.service
