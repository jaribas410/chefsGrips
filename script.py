import os
import glob
import time
import RPi.GPIO as GPIO
import pyttsx3

BtnPin = 11
meats = ["beef", "pork", "poultry", "lamb", "seafood"]
currentMeat = 0

TRIG = 11       
ECHO = 12       
BuzzerPin = 13 

THRESHOLDS = {
    "beef": [
        ("undercooked", 0),
        ("rare", 125),
        ("medium_rare", 135),
        ("medium", 145),
        ("medium_well", 150),
        ("well_done", 160),
    ],
    "lamb": [
        ("undercooked", 0),
        ("rare", 125),
        ("medium_rare", 135),
        ("medium", 145),
        ("medium_well", 150),
        ("well_done", 160),
    ],
    "pork": [
        ("undercooked", 0),
        ("medium", 145),
        ("medium_well", 150),
        ("well_done", 160),
    ],
    "poultry": [
        ("undercooked", 0),
        ("approaching_safe", 155),
        ("safe", 165),
        ("dry_overcooked", 175),
    ],
    "seafood": [
        ("undercooked", 0),
        ("medium", 125),
        ("safe_flaky", 145),
    ],
}

base_dir = "/sys/bus/w1/devices"
device_file = None
engine = pyttsx3.init()

def setup():
    """ Setup the GPIO pins for the ultrasonic sensor and buzzer """
    GPIO.setmode(GPIO.BOARD)
    
    # Setup for ultrasonic sensor
    GPIO.setup(TRIG, GPIO.OUT)
    GPIO.setup(ECHO, GPIO.IN)
    
    # Setup for buzzer
    GPIO.setup(BuzzerPin, GPIO.OUT)
    GPIO.output(BuzzerPin, GPIO.HIGH)
    
def buzzer_on():
    GPIO.output(BuzzerPin, GPIO.LOW)

def buzzer_off():
    GPIO.output(BuzzerPin, GPIO.HIGH)
    
def destroy():
    """ Cleanup function to reset GPIO settings """
    GPIO.cleanup()

def load_onewire():
    global device_file
    os.system("modprobe w1-gpio")
    os.system("modprobe w1-therm")
    candidates = glob.glob(os.path.join(base_dir, "28-*"))
    device_file = os.path.join(candidates[0], "w1_slave") if candidates else None

def read_rom():
    candidates = glob.glob(os.path.join(base_dir, "28-*"))
    if not candidates:
        return None
    name_path = os.path.join(candidates[0], "name")
    try:
        with open(name_path, "r") as f:
            return f.readline().strip()
    except FileNotFoundError:
        return None

def read_temp_raw():
    if device_file is None:
        return None
    with open(device_file, "r") as f:
        return f.readlines()

def read_temp_f():
    lines = read_temp_raw()
    if lines is None:
        return None
    retry = 0
    while lines[0].strip()[-3:] != "YES":
        time.sleep(0.05)
        lines = read_temp_raw()
        if lines is None:
            return None
        retry += 1
        if retry > 40:
            return None
    p = lines[1].find("t=")
    if p == -1:
        return None
    c = float(lines[1][p + 2:]) / 1000.0
    return (((c * 9.0 / 5.0) + 32.0) * 1.7)

def classify_temp(meat_name: str, t_f: float) -> str:
    tiers = THRESHOLDS.get(meat_name)
    if not tiers:
        return "unknown"
    state = tiers[0][0]
    for label, cutoff in tiers:
        if t_f >= cutoff:
            state = label
        else:
            break
    return state

def determine_cook(meat_index, temperature_f):
    meat_name = meats[meat_index]
    if temperature_f is None:
        print(f"[{meat_name}] Sensor not ready.")
        return
    state = classify_temp(meat_name, temperature_f)
    print(f"[{meat_name}] {temperature_f:.1f}°F → {state}")
    try:
        if meat_name in ("poultry", "seafood") and state in ("safe", "safe_flaky"):
            speak(f"{meat_name} has reached a safe temperature.")
            buzzer_on()
        elif meat_name in ("beef", "lamb", "pork") and state in ("medium", "well_done", "safe_flaky"):
            if meat_name == "pork" and tempeerature_f > 145:
                speak("Pork is at a safe temperature.")
                buzzer_on()
        else:
            buzzer_off()
    except Exception:
        pass

def speak(text):
    try:
        engine.say(text)
        engine.runAndWait()
    except Exception as e:
        print(f"[TTS] Error: {e}")

def switch_meat():
    global currentMeat
    currentMeat = (currentMeat + 1) % len(meats)
    msg = f"Switched meat to: {meats[currentMeat]}"
    print(msg)
    speak(msg)

def detect(channel):
    level = GPIO.input(BtnPin)
    print(f"[CB] Edge on pin {BtnPin}, level={level}")
    if level == 0:
        switch_meat()

def setup_gpio():
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(BtnPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    try:
        GPIO.remove_event_detect(BtnPin)
    except Exception:
        pass
    try:
        GPIO.add_event_detect(BtnPin, GPIO.FALLING, callback=detect, bouncetime=200)
        print("[GPIO] Interrupt attached on FALLING edge.")
    except RuntimeError as e:
        print(f"[GPIO] Failed to add edge detection (polling fallback): {e}")

def destroy():
    try:
        GPIO.cleanup()
    except Exception:
        pass

def main():
    try:
        load_onewire()
        rom = read_rom()
        if rom:
            print(f"Sensor ROM: {rom}")
        else:
            print("No DS18B20 sensor detected.")
        setup_gpio()
        last_level = GPIO.input(BtnPin)
        last_change = time.monotonic()
        debounce_s = 0.15
        print("Ready. With PUD_UP, wire button between pin 11 and GND.")
        next_temp_print = 0.0
        while True:
            now = time.monotonic()
            level = GPIO.input(BtnPin)
            if level != last_level:
                if (now - last_change) >= debounce_s:
                    print(f"[POLL] Pin {BtnPin} changed: {last_level} -> {level}")
                    last_level = level
                    if level == 0:
                        switch_meat()
                last_change = now
            if now >= next_temp_print:
                temp_f = read_temp_f()
                determine_cook(currentMeat, temp_f)
                next_temp_print = now + 1.5
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        destroy()

if __name__ == "__main__":
    main()
