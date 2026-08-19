import serial
import serial.tools.list_ports
import re
import pygame
import sys
import time

# ---- Configuracion ----
PUERTO = "COM3"  # cambia esto por tu puerto COM real
BAUD = 115200
ANCHO, ALTO = 1300, 750
ANCHO_RADAR = 850
ESCALA = 0.2
CENTRO_X, CENTRO_Y = ANCHO_RADAR // 2, 150
TIEMPO_EXPIRACION_MS = 800
SUAVIZADO = 0.25
MAX_LINEAS_LOG = 26
DURACION_ALERTA_MS = 4000
INTERVALO_RECONEXION_MS = 2000

patron_posicion = re.compile(r"Obj (\d+) -> X=(-?\d+)\s+mm Y=(-?\d+)\s+mm V=(-?\d+\.?\d*)\s+cm/s")

# ---- Pygame ----
pygame.init()
pantalla = pygame.display.set_mode((ANCHO, ALTO))
pygame.display.set_caption("Wi-Care - Dashboard en vivo")
fuente_titulo = pygame.font.SysFont("consolas", 30, bold=True)
fuente_subtitulo = pygame.font.SysFont("consolas", 14)
fuente = pygame.font.SysFont("consolas", 18)
fuente_log = pygame.font.SysFont("consolas", 13)
fuente_estado = pygame.font.SysFont("consolas", 26, bold=True)
fuente_grande = pygame.font.SysFont("consolas", 40, bold=True)
reloj = pygame.time.Clock()

NEGRO = (10, 10, 15)
VERDE = (0, 220, 100)
AMARILLO = (240, 190, 30)
ROJO = (230, 30, 30)
GRIS = (60, 60, 70)
GRIS_CLARO = (140, 140, 150)
BLANCO = (230, 230, 230)
GRIS_LOG = (0, 255, 90)
FONDO_LOG = (5, 12, 8)
FONDO_HEADER = (18, 18, 26)

# ---- Logo ----
try:
    logo_original = pygame.image.load("logo.png").convert_alpha()
    alto_logo = 44
    proporcion = alto_logo / logo_original.get_height()
    ancho_logo = int(logo_original.get_width() * proporcion)
    logo = pygame.transform.smoothscale(logo_original, (ancho_logo, alto_logo))
except Exception as e:
    logo = None
    print(f"No se pudo cargar el logo: {e}")

# ---- Estado del sistema ----
objetivos = {}
alerta_activa = False
tiempo_ultima_alerta = 0
confirmando_caida = False
log_lineas = []

# ---- Estado de conexion ----
ser = None
conectado = False
ultimo_intento_conexion = 0


def intentar_conectar():
    global ser, conectado
    try:
        ser = serial.Serial(PUERTO, BAUD, timeout=0.05)
        conectado = True
        log_lineas.append(f"[SISTEMA] Conectado a {PUERTO}")
        print(f"Conectado a {PUERTO}")
    except Exception as e:
        conectado = False
        ser = None


def mm_a_pantalla(x_mm, y_mm):
    return CENTRO_X + int(x_mm * ESCALA), CENTRO_Y + int(y_mm * ESCALA)


def dibujar_header():
    pygame.draw.rect(pantalla, FONDO_HEADER, (0, 0, ANCHO_RADAR, 60))
    pygame.draw.line(pantalla, GRIS, (0, 60), (ANCHO_RADAR, 60), 1)

    x_texto = 16
    if logo:
        pantalla.blit(logo, (16, 8))
        x_texto = 16 + logo.get_width() + 12

    titulo = fuente_titulo.render("WI-CARE", True, BLANCO)
    pantalla.blit(titulo, (x_texto, 8))
    subtitulo = fuente_subtitulo.render("Sistema de monitoreo y deteccion de caidas", True, GRIS_CLARO)
    pantalla.blit(subtitulo, (x_texto, 38))

    color_conexion = VERDE if conectado else ROJO
    texto_conexion = "CONECTADO" if conectado else "SIN CONEXION"
    superficie_conexion = fuente_subtitulo.render(texto_conexion, True, color_conexion)
    pantalla.blit(superficie_conexion, (ANCHO_RADAR - superficie_conexion.get_width() - 16, 22))


def dibujar_radar_de_fondo():
    for radio_mm in [500, 1000, 1500, 2000, 2500, 3000]:
        pygame.draw.circle(pantalla, GRIS, (CENTRO_X, CENTRO_Y), int(radio_mm * ESCALA), 1)
    pygame.draw.line(pantalla, GRIS, (CENTRO_X, 60), (CENTRO_X, ALTO), 1)
    pygame.draw.line(pantalla, GRIS, (0, CENTRO_Y), (ANCHO_RADAR, CENTRO_Y), 1)
    pygame.draw.circle(pantalla, BLANCO, (CENTRO_X, CENTRO_Y), 8)
    pantalla.blit(fuente.render("RADAR", True, BLANCO), (CENTRO_X + 12, CENTRO_Y - 10))


def dibujar_estado():
    ahora = pygame.time.get_ticks()
    if alerta_activa:
        parpadeo = (ahora // 300) % 2 == 0
        color = ROJO if parpadeo else (120, 15, 15)
        texto = "ALERTA DE CAIDA"
    elif confirmando_caida:
        color = AMARILLO
        texto = "CONFIRMANDO POSIBLE CAIDA..."
    elif not conectado:
        color = GRIS_CLARO
        texto = "ESPERANDO CONEXION..."
    else:
        color = VERDE
        texto = "MONITOREO NORMAL"

    superficie = fuente_estado.render(texto, True, color)
    rect = superficie.get_rect(center=(ANCHO_RADAR // 2, ALTO - 30))
    pantalla.blit(superficie, rect)


def dibujar_panel_log():
    x0 = ANCHO_RADAR
    pygame.draw.rect(pantalla, FONDO_LOG, (x0, 0, ANCHO - ANCHO_RADAR, ALTO))
    pygame.draw.line(pantalla, GRIS, (x0, 0), (x0, ALTO), 2)
    titulo = fuente.render("MONITOR SERIAL", True, BLANCO)
    pantalla.blit(titulo, (x0 + 12, 10))
    pygame.draw.line(pantalla, GRIS, (x0 + 10, 36), (ANCHO - 10, 36), 1)

    y = 46
    for linea in log_lineas[-MAX_LINEAS_LOG:]:
        color = ROJO if ("ALERTA" in linea) else (AMARILLO if "BURST" in linea or "confirmacion" in linea else GRIS_LOG)
        superficie = fuente_log.render(linea[:60], True, color)
        pantalla.blit(superficie, (x0 + 10, y))
        y += 18


def leer_serial():
    global conectado, alerta_activa, tiempo_ultima_alerta, confirmando_caida, objetivos

    if not conectado or ser is None:
        return

    ahora = pygame.time.get_ticks()
    try:
        while ser.in_waiting:
            linea = ser.readline().decode("utf-8", errors="ignore").strip()
            if not linea:
                continue

            log_lineas.append(linea)
            if len(log_lineas) > 500:
                del log_lineas[:250]

            match = patron_posicion.search(linea)
            if match:
                obj_num = int(match.group(1))
                x = int(match.group(2))
                y = int(match.group(3))
                v = float(match.group(4))

                if obj_num not in objetivos:
                    objetivos[obj_num] = {"x_disp": float(x), "y_disp": float(y), "v": v, "ultima_act": ahora}
                else:
                    d = objetivos[obj_num]
                    d["x_disp"] += (x - d["x_disp"]) * SUAVIZADO
                    d["y_disp"] += (y - d["y_disp"]) * SUAVIZADO
                    d["v"] = v
                    d["ultima_act"] = ahora

            if "iniciando confirmacion de posible caida" in linea:
                confirmando_caida = True
            if "se movio/recupero" in linea or "caida descartada" in linea:
                confirmando_caida = False
            if "ALERTA CAIDA" in linea:
                alerta_activa = True
                confirmando_caida = False
                tiempo_ultima_alerta = ahora

    except (serial.SerialException, OSError):
        conectado = False
        try:
            ser.close()
        except Exception:
            pass


intentar_conectar()

corriendo = True
while corriendo:
    for evento in pygame.event.get():
        if evento.type == pygame.QUIT:
            corriendo = False

    ahora = pygame.time.get_ticks()

    if not conectado and ahora - ultimo_intento_conexion > INTERVALO_RECONEXION_MS:
        ultimo_intento_conexion = ahora
        intentar_conectar()

    leer_serial()

    objetivos = {k: v for k, v in objetivos.items() if ahora - v["ultima_act"] < TIEMPO_EXPIRACION_MS}

    if alerta_activa and ahora - tiempo_ultima_alerta > DURACION_ALERTA_MS:
        alerta_activa = False

    pantalla.fill(NEGRO)
    dibujar_header()
    dibujar_radar_de_fondo()

    for num, d in objetivos.items():
        px, py = mm_a_pantalla(d["x_disp"], d["y_disp"])
        color = ROJO if alerta_activa else (AMARILLO if confirmando_caida else VERDE)
        pygame.draw.circle(pantalla, color, (px, py), 14)
        etiqueta = fuente.render(f"Obj {num}  V={d['v']:.1f}cm/s", True, BLANCO)
        pantalla.blit(etiqueta, (px + 18, py - 10))

    if alerta_activa:
        parpadeo = (ahora // 300) % 2 == 0
        if parpadeo:
            texto_alerta = fuente_grande.render("ALERTA DE CAIDA", True, ROJO)
            rect = texto_alerta.get_rect(center=(ANCHO_RADAR // 2, ALTO - 80))
            pantalla.blit(texto_alerta, rect)

    dibujar_estado()
    dibujar_panel_log()

    pygame.display.flip()
    reloj.tick(90)

pygame.quit()
if ser:
    ser.close()
sys.exit()