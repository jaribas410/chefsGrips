import os
import glob
import time
import RPi.GPIO as GPIO
import pyttsx3

engine = pyttsx3.init()

BtnPin = 11                    # BOARD numbering; physical pin 11 (GPIO17)
meats = ["beef", "pork", "poultry", "lamb", "seafood"]
currentMeat = 0

BEEF_THRESHOLDS = {
    "undercooked": 0,
    "rare": 125,
    "medium_rare": 130,
    "medium": 145,
    "medium_well": 150,
    "well_done": 160,
}

base_dir = "/sys/bus/w1/devices"
device_file = None

def load_onewire():
    global device_file
    os.system("modprobe w1-gpio")
    os.system("modprobe w1-therm")
    candidates = glob.glob(os.path.join(base_dir, "28-*"))
    device_file = os.path.join(candidates[0], "w1_slave") if candidates else None

def read_rom():
    candidates = glob.glob(os.path.join(base_dir, "28-*"))
    if not candidates: return None
    name_path = os.path.join(candidates[0], "name")
    try:
        with open(name_path, "r") as f:
            return f.readline().strip()
    except FileNotFoundError:
        return None

def read_temp_raw():
    if device_file is None: return None
    with open(device_file, "r") as f:
        return f.readlines()

def read_temp_f():
    lines = read_temp_raw()
    if lines is None: return None
    retry = 0
    while lines[0].strip()[-3:] != "YES":
        time.sleep(0.05)
        lines = read_temp_raw()
        if lines is None: return None
        retry += 1
        if retry > 40:   # ~2s
            return None
    p = lines[1].find("t=")
    if p == -1: return None
    c = float(lines[1][p+2:]) / 1000.0
    return (c * 9.0 / 5.0) + 32.0

def determine_cook(meat_index, temperature_f):
    meat_name = meats[meat_index]
    if temperature_f is None:
        print(f"[{meat_name}] Sensor not ready.")
        return
    if meat_name == "beef":
        t = temperature_f
        if t > BEEF_THRESHOLDS["well_done"]:
            state = "overcooked"
        elif t > BEEF_THRESHOLDS["medium_well"]:
            state = "well done"
        elif t > BEEF_THRESHOLDS["medium"]:
            state = "medium well"
        elif t > BEEF_THRESHOLDS["medium_rare"]:
            state = "medium"
        elif t > BEEF_THRESHOLDS["rare"]:
            state = "medium rare"
        elif t > BEEF_THRESHOLDS["undercooked"]:
            state = "rare"
        else:
            state = "undercooked"
        print(f"[{meat_name}] {t:.1f}°F → {state}")
    else:
        print(f"[{meat_name}] {temperature_f:.1f}°F (add thresholds)")

def switch_meat():
    global currentMeat
    currentMeat = (currentMeat + 1) % len(meats)
    engine.say(f"Switched meat to: {meats[currentMeat]}")

def detect(channel):
    # Callback (edge-detect) path
    level = GPIO.input(BtnPin)
    print(f"[CB] Edge on pin {BtnPin}, level={level}")
    # With PUD_UP, a press pulls to GND (level 0). Switch on press.
    if level == 0:
        switch_meat()

def setup_gpio():
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(BtnPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    # Use BOTH edges so we can log transitions; act on press (level==0)
    GPIO.add_event_detect(BtnPin, GPIO.BOTH, callback=detect, bouncetime=200)

def destroy():
    GPIO.cleanup()

def main():
    try:
        engine.runAndWait()
        load_onewire()
        rom = read_rom()
        if rom:
            print(f"Sensor ROM: {rom}")
        else:
            print("No DS18B20 sensor detected.")

        setup_gpio()

        # Polling debounce fallback (works even if callbacks fail)
        last_level = GPIO.input(BtnPin)
        last_change = time.monotonic()
        debounce_s = 0.15       # 150 ms debounce
        next_temp_print = 0.0   # immediate first print

        print("Ready. With PUD_UP, wire button between pin 11 and GND.")
        while True:
            now = time.monotonic()

            # Poll the button quickly
            level = GPIO.input(BtnPin)
            if level != last_level:
                # state changed; debounce window
                if (now - last_change) >= debounce_s:
                    print(f"[POLL] Pin {BtnPin} changed: {last_level} -> {level}")
                    last_change = now
                    last_level = level
                    # act on press (goes low with PUD_UP)
                    if level == 0:
                        switch_meat()

            # Print temperature every 1.5s
            if now >= next_temp_print:
                temp_f = read_temp_f()
                determine_cook(currentMeat, temp_f)
                next_temp_print = now + 1.5

            time.sleep(0.01)  # keep loop responsive
	
    except KeyboardInterrupt:
        pass
    finally:
        destroy()

if __name__ == "__main__":
    main()
