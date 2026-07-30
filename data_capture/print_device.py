import sounddevice as sd
for index, device in enumerate(sd.query_devices()):
    if device['max_input_channels'] > 0:
        api = sd.query_hostapis(device['hostapi'])['name']
        print(f"{index:3d}  {api:12s}  {device['name']}")
