import os
import glob
import time
import RPi.GPIO as GPIO
import pyttsx3

#---------------------------
# Pins (BOARD numbering)
#---------------------------
BtnPin=11
BuzzerPin=13
TRIG=16
ECHO=18

#---------------------------
# Meat thresholds (°F)
#---------------------------
meats=["beef","pork","poultry","lamb","seafood"]
currentMeat=0
THRESHOLDS={
	"beef":[
		("undercooked",0),
		("rare",125),
		("medium_rare",135),
		("medium",145),
		("medium_well",150),
		("well_done",160),
	],
	"lamb":[
		("undercooked",0),
		("rare",125),
		("medium_rare",135),
		("medium",145),
		("medium_well",150),
		("well_done",160),
	],
	"pork":[
		("undercooked",0),
		("medium",145),
		("medium_well",150),
		("well_done",160),
	],
	"poultry":[
		("undercooked",0),
		("approaching_safe",155),
		("safe",165),
		("dry_overcooked",175),
	],
	"seafood":[
		("undercooked",0),
		("medium",125),
		("safe_flaky",145),
	],
}

#---------------------------
# DS18B20 1-Wire
#---------------------------
base_dir="/sys/bus/w1/devices"
device_file=None

#---------------------------
# TTS
#---------------------------
engine=pyttsx3.init()

def speak(text:str)->None:
	try:
		engine.say(text)
		engine.runAndWait()
	except Exception as e:
		print(f"[TTS] Error:{e}")

def buzzer_on():
	GPIO.output(BuzzerPin,GPIO.HIGH)  # active low

def buzzer_off():
	GPIO.output(BuzzerPin,GPIO.LOW)

def load_onewire():
	global device_file
	try:
		os.system("modprobe w1-gpio")
		os.system("modprobe w1-therm")
	except Exception:
		pass
	candidates=glob.glob(os.path.join(base_dir,"28-*"))
	device_file=os.path.join(candidates[0],"w1_slave") if candidates else None

def read_rom():
	candidates=glob.glob(os.path.join(base_dir,"28-*"))
	if not candidates:
		return None
	name_path=os.path.join(candidates[0],"name")
	try:
		with open(name_path,"r") as f:
			return f.readline().strip()
	except FileNotFoundError:
		return None

def read_temp_raw():
	if device_file is None:
		return None
	try:
		with open(device_file,"r") as f:
			return f.readlines()
	except Exception:
		return None

def read_temp_f():
	lines=read_temp_raw()
	if lines is None:
		return None
	retry=0
	while lines and not lines[0].strip().endswith("YES"):
		time.sleep(0.05)
		lines=read_temp_raw()
		if lines is None:
			return None
		retry+=1
		if retry>40:
			return None
	if not lines or len(lines)<2:
		return None
	p=lines[1].find("t=")
	if p==-1:
		return None
	c=float(lines[1][p+2:])/1000.0
	f=(c*9.0/5.0)+32.0
	return f * 1.5

def classify_temp(meat_name:str,t_f:float)->str:
	tiers=THRESHOLDS.get(meat_name)
	if not tiers:
		return "unknown"
	state=tiers[0][0]
	for label,cutoff in tiers:
		if t_f>=cutoff:
			state=label
		else:
			break
	return state

#---------------------------
# Cook targets (menu-selected)
#---------------------------
# selected_targets[meat_name]=cutoff°F or None
selected_targets={m:None for m in meats}
# selected_indices[meat_name]=index in THRESHOLDS list for menu cycling
selected_indices={m:1 for m in meats}  # start at first meaningful tier

def current_tiers(meat_name:str):
	return THRESHOLDS[meat_name]

def next_valid_index(meat_name:str,idx:int)->int:
	# skip index 0 ("undercooked") when cycling
	tiers=current_tiers(meat_name)
	if len(tiers)<=1:
		return 0
	idx=(idx+1)%len(tiers)
	if idx==0:
		idx=1
	return idx

def determine_cook(meat_index:int,temperature_f:float,cook_menu_open:bool)->None:
	meat_name=meats[meat_index]
	if temperature_f is None:
		print(f"[{meat_name}] Sensor not ready.")
		buzzer_off()
		return
	state=classify_temp(meat_name,temperature_f)
	print(f"[{meat_name}] {temperature_f:.1f}°F→{state}")

	try:
		target=selected_targets.get(meat_name)
		if target is None:
		    label, cutoff = THRESHOLDS["beef"][1]  # ('rare', 125)
		    selected_indices["beef"] = 1
		    selected_targets["beef"] = cutoff
		    target = cutoff
		if target is not None:
			if temperature_f>=target:
				label=next(l for l,v in THRESHOLDS[meat_name] if v==target)
				speak(f"{meat_name} reached target{label}.")
				buzzer_on()
			else:
				buzzer_off()
			return
		alert=False
		if meat_name=="poultry" and state in ("safe",):
			speak("Poultry has reached a safe temperature.")
			alert=True
		elif meat_name=="seafood" and state in ("safe_flaky",):
			speak("Seafood is done and flaky.")
			alert=True
		elif meat_name=="pork" and temperature_f>=145:
			speak("Pork is at a safe temperature.")
			alert=True
		elif meat_name in ("beef","lamb"):
			if state in ("medium","medium_well","well_done"):
				speak(f"The {meat_name} has reached {state}.")
				alert=True
		if alert:
			buzzer_on()
		else:
			buzzer_off()
	except Exception as e:
		print(f"[determine_cook] Error:{e}")
		buzzer_off()

def switch_meat():
	global currentMeat
	currentMeat=(currentMeat+1)%len(meats)
	msg=f"Switched meat to {meats[currentMeat]}"
	print(msg)
	speak(msg)

def switch_cook():
	meat=meats[currentMeat]
	tiers=current_tiers(meat)
	# advance index (skip 'undercooked' at 0)
	idx=next_valid_index(meat,selected_indices[meat])
	selected_indices[meat]=idx
	label,cutoff=tiers[idx]
	selected_targets[meat]=cutoff
	print(f"[CookMenu] {meat} target→{label}({cutoff}°F)")
	speak(f"{meat} target {label}")

def setup_gpio():
	GPIO.setwarnings(False)
	GPIO.setmode(GPIO.BOARD)
	GPIO.setup(BtnPin,GPIO.IN,pull_up_down=GPIO.PUD_UP)
	GPIO.setup(BuzzerPin,GPIO.OUT, initial=GPIO.LOW)
	GPIO.output(BuzzerPin,GPIO.HIGH)
	GPIO.setup(TRIG,GPIO.OUT,initial=GPIO.LOW)
	GPIO.setup(ECHO,GPIO.IN)

def cleanup():
	try:
		buzzer_off()
		GPIO.cleanup()
	except Exception:
		pass

def main():
	try:
		load_onewire()
		rom=read_rom()
		if rom:
			print(f"Sensor ROM:{rom}")
		else:
			print("No DS18B20 sensor detected.")
		setup_gpio()
		print("Ready. Short press:cycle meat. Long press(≥2s):toggle cook menu.")
		cook_menu_open=False
		hold_threshold=2.0
		last_state=GPIO.input(BtnPin)
		press_start=None
		next_print=0.0

		while True:
			now=time.monotonic()
			state=GPIO.input(BtnPin)  # 1=pulled-up(released),0=pressed

			# Rising/Falling detection via polling
			if last_state==1 and state==0:
				# pressed
				press_start=now
			elif last_state==0 and state==1 and press_start is not None:
				# released
				held=now-press_start
				if held>=hold_threshold:
					# toggle menu
					cook_menu_open=not cook_menu_open
					if cook_menu_open:
						m=meats[currentMeat]
						lbl,cut=THRESHOLDS[m][selected_indices[m]]
						print("[CookMenu]OPEN")
						speak("Cook menu open")
						speak(f"{m} target {lbl}")
						print(f"[CookMenu] {m} target→{lbl}({cut}°F)")
					else:
						print("[CookMenu]CLOSE")
						speak("Cook menu closed")
				else:
					# short press behavior
					if cook_menu_open:
						switch_cook()
					else:
						switch_meat()
				press_start=None

			last_state=state

			# periodic temperature evaluation
			if now>=next_print:
				temp_f=read_temp_f()
				determine_cook(currentMeat,temp_f,cook_menu_open)
				next_print=now+1.5

			time.sleep(0.01)

	except KeyboardInterrupt:
		pass
	finally:
		cleanup()

if __name__=="__main__":
	main()
