import serial

PUERTO = "COM3"  # cambia esto por tu numero de COM real
BAUD = 115200

ser = serial.Serial(PUERTO, BAUD, timeout=1)
print(f"Conectado a {PUERTO}")

while True:
    linea = ser.readline().decode("utf-8", errors="ignore").strip()
    if linea:
        print(linea)