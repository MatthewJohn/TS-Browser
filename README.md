# Transport Stream Browser

This application provides a basic web interface for viewing details about transport streams held on a server (presumably a central file sever)

### Install dependencies

    # Python libraries
    sudo apt-get install python-flask python-watchdog python-humanize
    # Install Tools for analysis
    sudo apt-get install vlc ffmpeg

### 'Configure'

Edit 'server.py', and update 'TS_DIR' to the base path where your transport stream files are stored.
Note: Write access is required to the transport stream directory, as metadata is written to files next to the transport streams.

You may with to toggle ''debug=True'' -> ''debug=False'' in the def start() of the WebServer class.

You may wish to also toggle ''threaded=True'' in the self.app.start() in start() of the WebServer class.

### Run

    python ./server.py

## Screenshots

Directory listing

![Directory listing](/images/dir_list.png?raw=true "")

Transport Stream information

![Directory listing](/images/ts_info.png?raw=true "")
 
# LICENSE
TransportStreamCatalgoue is licensed under GPL v2. For more information, please see LICENSE

# COPYRIGHT
Copyright © 2016 - Matt Comben
