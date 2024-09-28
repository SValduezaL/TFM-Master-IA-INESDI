'''
Asistente Virtual Basilio para MediAgendaSolutions
'''

# Importar las bibliotecas necesarias para interactuar con OpenAI y manejar eventos
from openai import OpenAI, AssistantEventHandler

# Importar bibliotecas para manejar el tiempo y las fechas
import time as t
from datetime import datetime, time, timedelta
from typing import Dict, List, Union

# Importar bibliotecas para manejar JSON y el sistema de archivos
import json
import os
import logging

# Importar override para facilitar la anotación de métodos en clases
from typing_extensions import override

# Importar gspread para interactuar con Google Sheets
import gspread
from google.oauth2.service_account import Credentials

# Importar bibliotecas de Telegram para manejar actualizaciones y mensajes
from telegram import Update, Bot, ChatAction
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext

# Importar excepciones para manejar errores en las solicitudes
from requests.exceptions import RequestException

# Inicializar el cliente de OpenAI con la clave API proporcionada
client = OpenAI(api_key='sk-proj-Uced5j5iSx13bk7IUtbLT3BlbkFJmJpHhTPQDRZaLtuivsUc')
ASSISTANT_ID = 'asst_BGagd32hcZB3h8WlNvX2J1ku' # MediAgenda Solutions
assistant = client.beta.assistants.retrieve(assistant_id=ASSISTANT_ID)

# Inicializar el cliente de Telegram con el token del bot
# TELEGRAM_TOKEN = '7365309172:AAHkGNnXzUPHyv8-Mo5VgiorIWTvIm_NXSo' # https://t.me/MediAgendaBot
TELEGRAM_TOKEN = '7193381473:AAHNVUdTBPXKCB0rMXGeOwsY53r90nG6eyg' # https://t.me/Basilio_MediAgenda_bot

# Función para mostrar JSON en consola, usada para depuración
def show_json(obj):
    '''
    Muestra un objeto json en consola
    '''
    print(json.loads(obj.model_dump_json()))

# Configuración de credenciales de Google Sheets para acceder a las hojas de cálculo
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# creds = Credentials.from_service_account_file('C:\\Users\\nerea\\Downloads\\mediagenda-solutions-5e8208b2d6a6.json', scopes=scope)

# Obtener el directorio del script
script_dir = os.path.dirname(os.path.abspath(__file__))
# Construir la ruta al archivo JSON basado en el directorio del script
json_path = os.path.join(script_dir, 'mediagenda-solutions-5e8208b2d6a6.json')
# Credenciales
creds = Credentials.from_service_account_file(json_path, scopes = scope)

client_gspread = gspread.authorize(creds)

# ID de la hoja de cálculo de Google Sheets
SPREADSHEET_ID = '1QXAV39MG5pE9JD7YW4H3bJowMXoI72bjvcD4MBN7Jww'

# Abrir la hoja de cálculo por su ID y seleccionar las hojas necesarias
spreadsheet = client_gspread.open_by_key(SPREADSHEET_ID)
agenda_worksheet = spreadsheet.sheet1  # Hoja para agendar citas
medico_worksheet = spreadsheet.get_worksheet(1)  # Hoja con médicos y especialidades

def buscar_medicos_especialidades(
    identificador: str,
    tipo_busqueda: str = "especialidad"
) -> list[str]:
    '''
    Busca el/los médicos por especialidad, o la/las especialidades por médico.

    Args:
        identificador (str): Nombre de las Especialidades o de los Médicos a buscar.
        por (str): Tipo de búsqueda (por "especialidad", o por "medico").
            Por defecto = "especialidad"
    
    Returns:
        list[str]: Conjunto con los nombres de los médicos o de las especialidades,
                    según el caso. Conjunto vacío si no se encuentra nada.
    '''
    # Obtener todas las filas de la hoja medico_worksheet
    all_rows = medico_worksheet.get_all_values()

    if tipo_busqueda == "especialidad":
        # Buscar la fila donde la primera columna coincide con la especialidad
        medicos = list({row[1] for row in all_rows if row[0] == identificador})
        return medicos

    if tipo_busqueda == "medico":
        # Buscar la fila donde la segunda columna coincide con el nombre del médico
        especialidades = list({row[0] for row in all_rows if row[1] == identificador})
        return especialidades

    # Retornar lista vacía si no hay coincidencias
    return []

def redondear_a_multiplo_20_minutos(hora_str: str) -> str:
    """
    Redondea una hora al múltiplo de 20 minutos más cercano.

    Args:
        hora_str (str): Hora en formato 'HH:MM'.

    Returns:
        str: Hora redondeada en formato 'HH:MM'.
    """
    # Convertir la cadena de hora a un objeto datetime
    hora_dt = datetime.strptime(hora_str, '%H:%M')
    # Obtener los minutos actuales
    minutos = hora_dt.minute
    # Calcular el múltiplo de 20 minutos más cercano
    minutos_redondeados = round(minutos / 20) * 20
    # Asegurarse de que los minutos redondeados estén en el rango 0-59
    if minutos_redondeados == 60:
        minutos_redondeados = 0
        hora_dt += timedelta(hours=1)
    # Crear una nueva hora con los minutos redondeados
    hora_redondeada = hora_dt.replace(minute=minutos_redondeados, second=0, microsecond=0)
    # Devolver la hora redondeada en formato de cadena
    return hora_redondeada.strftime('%H:%M')

# Función para verificar y obtener médicos libres a la hora especificada
def comprobar_si_hay_medicos_libres(
    medicos: list[str],
    citas_reservadas: list(tuple[str, str, str]),
    fecha: str,
    hora: str
) -> tuple[bool, list[str]]:
    '''
    Verifica si hay médicos libres para una fecha y hora específicas.

    Args:
        medicos (set[str]): Conjunto de médicos disponibles a comprobar.
        citas_reservadas (list): Lista de citas reservadas, donde cada cita es una tupla de
                                    (médico, fecha, hora)
        fecha (str): Fecha de la cita en formato YYYY-MM-DD.
        hora (str): Hora de la cita en formato HH:MM.

    Returns: Tupla con un booleano indicando si hay médicos libres
                y una lista con los médicos libres.
    '''
    
    # Crear un conjunto de médicos que tienen citas reservadas para la fecha y hora especificadas
    medicos_con_citas_reservadas = set(
        cita[0] for cita in citas_reservadas # Extraer el nombre del médico de cada cita
        if cita[1] == fecha and cita[2] == hora # Filtrar citas que coincidan con la fecha y hora
    )
    
    # Obtener la lista de médicos libres restando los que tienen citas reservadas
    medicos_libres = list(set(medicos) - medicos_con_citas_reservadas)
    
    # Verificar si hay médicos libres, convirtiendo la lista en un booleano
    hay_medicos_libres = bool(medicos_libres)
    
    # Devolver una tupla con el resultado de la verificación y la lista de médicos libres
    return (hay_medicos_libres, medicos_libres)
    
def verificar_disponibilidad(
    fecha: str,
    identificador: str,
    hora: str = "",
    tipo_verificacion: str = "especialidad"
) -> Dict[str, Union[bool, List[str], List[str], str]]:
    '''
    Verifica la disponibilidad para una cita médica en una fecha
    (y hora, opcional) específicas.
    
    Args:
        tipo_verificacion (str, opcional): Define el tipo de verificación. Puede ser:
            "especialidad": Busca la disponibilidad por especialidad médica (por defecto).
            "medico": Busca la disponibilidad por un médico específico.
        identificador (str): Dependiendo del valor de tipo_verificación, especifica la
            especialidad médica o el nombre del médico.
        fecha (str): Fecha de la cita en formato YYYY-MM-DD.
        hora (str, opcional): Hora de la cita en formato HH:MM.
            Por defecto = "". Al no especificar buscará todas las horas disponibles para esa fecha.

    Returns:
        Dict: Un dicionario con las siguientes claves:
            "existe_disponibilidad" (bool):
                True: Existe disponibilidad para la fecha (y hora) indicadas.
                False: No existe disponibilidad para la fecha (y hora) indicadas.
            "medicos_libres" (List[str]): Lista de los médicos disponibles en esa fecha y hora.
            "horas_disponibles" (List[str]): Lista con las horas disponibles en la fecha indicada.
            "mensaje" (str): Mensaje de error o informativo.
    '''
    
    # Definir las horas de inicio y fin del horario de atención
    hora_inicio_dt = time(8, 0)  # 8:00 AM
    hora_fin_dt = time(19, 0)   # 7:00 PM
    duracion_cita = timedelta(minutes=20) # Cada cita dura 20 minutos
    
    # Verificación basada en especialidad o médico
    if tipo_verificacion == "especialidad":
        # Si se busca por especialidad, obtener la lista de médicos disponibles
        medicos = buscar_medicos_especialidades(identificador, tipo_busqueda = "especialidad")
        if not medicos: # Si no se encuentran médicos para esa especialidad
            return {
                "existe_disponibilidad": False,
                "medicos_libres": [],
                "horas_disponibles": [],
                "mensaje": f"No disponemos de médicos para dicha especialidad ({identificador})."
            }
    else:
        # Si se busca por médico, verificar que el médico exista
        medicos = []
        all_rows = medico_worksheet.get_all_values() # Obtener todas las filas de la hoja de cálculo
        for row in all_rows:
            if row[1] == identificador: # Buscar por el nombre del médico
                medicos.append(identificador)
                break
        if not medicos: # Si no se encuentra el médico
            return {
                "existe_disponibilidad": False,
                "medicos_libres": [],
                "horas_disponibles": [],
                "mensaje": f"No disponemos del médico {identificador} en nuestra Clínica."
            }

    # Obtener las citas ya reservadas para la fecha y médicos indicados
    citas_reservadas = [
        (row[1], row[5], row[6]) # Tuplas con el nombre del médico, fecha y hora de la cita
        for row in agenda_worksheet.get_all_values() # Obtener todas las filas de la agenda
        if row[1] in medicos and row[5] == fecha and row[7].lower() != 'cancelada' # Filtrar por fecha y médico
    ]

     # Si no se especifica una hora, devolver todas las horas disponibles para la fecha
    if not hora:
        horas_disponibles = [] # Lista para almacenar las horas disponibles
        medicos_libres = set() # Conjunto de médicos disponibles en algún horario
        # Comenzar a verificar las horas disponibles desde las 8:00 AM
        hora_actual_dt = datetime.combine(datetime.strptime(fecha, '%Y-%m-%d'), hora_inicio_dt)
        
        # Iterar sobre todas las horas entre las 8:00 AM y las 7:00 PM, en intervalos de 20 minutos
        while hora_actual_dt.time() < hora_fin_dt:
            hora_actual_str = hora_actual_dt.strftime('%H:%M') # Formatear la hora actual como string
            for medico in medicos:
                # Verificar si el médico está disponible en esa hora
                if (medico, fecha, hora_actual_str) not in citas_reservadas:
                    medicos_libres.add(medico) # Agregar el médico disponible
                    if hora_actual_str not in horas_disponibles:
                        horas_disponibles.append(hora_actual_str) # Agregar la hora disponible
            hora_actual_dt += duracion_cita # Incrementar la hora en 20 minutos
            
        # Si se encontraron horas disponibles, devolver True con la lista de horas y médicos disponibles
        if horas_disponibles:
            return {
                "existe_disponibilidad": True,
                "medicos_libres": list(medicos_libres),
                "horas_disponibles": horas_disponibles,
                "mensaje": f"Para la fecha {fecha} hay horarios disponibles: {horas_disponibles}."
            }
            
        # Si no hay horas disponibles, devolver False
        return {
            "existe_disponibilidad": False,
            "medicos_libres": [],
            "horas_disponibles": [],
            "mensaje": f"Para la fecha {fecha} no hay horarios disponibles."
        }

    # Si se especifica una hora, verificar la disponibilidad en esa hora
    # Redondear la hora al múltiplo de 20 minutos más cercano
    hora_redondeada = redondear_a_multiplo_20_minutos(hora)
    hora_actual_redondeada_dt = datetime.strptime(hora_redondeada, '%H:%M').time()

    # Verificar si la hora solicitada es válida dentro del horario de atención
    if not hora_inicio_dt <= hora_actual_redondeada_dt < hora_fin_dt:
        return {
            "existe_disponibilidad": False,
            "medicos_libres": [],
            "horas_disponibles": [],
            "mensaje": "Hora no válida. Por favor elige una hora dentro del horario de atención."
        }
        
    # Comprobar si hay médicos disponibles en la hora redondeada
    hay_medicos_libres, medicos_libres = comprobar_si_hay_medicos_libres(
        medicos = medicos,
        citas_reservadas = citas_reservadas,
        fecha = fecha,
        hora = hora_redondeada
    )

   # Si hay médicos disponibles en esa hora, devolver True
    if hay_medicos_libres:
        return {
            "existe_disponibilidad": True,
            "medicos_libres": list(medicos_libres),
            "horas_disponibles": [hora_redondeada],
            "mensaje": f"Hay hora disponible a las {hora_redondeada} con {medicos_libres}."
        }

    # Si la hora está ocupada, buscar la siguiente hora disponible en el día
    fecha_actual_dt = datetime.strptime(fecha, '%Y-%m-%d')
    hora_actual_dt = datetime.combine(fecha_actual_dt, hora_actual_redondeada_dt) + duracion_cita
    
    # Continuar buscando horas disponibles hasta el cierre de la clínica
    while hora_actual_dt.time() < hora_fin_dt:
        hora_actual_str = hora_actual_dt.strftime('%H:%M')
        hay_medicos_libres, medicos_libres = comprobar_si_hay_medicos_libres(
            medicos = medicos,
            citas_reservadas = citas_reservadas,
            fecha = fecha,
            hora = hora_actual_str
        )

        # Si se encuentra una hora disponible, devolver False pero indicar la siguiente hora libre
        if hay_medicos_libres:
            mensaje = (
                f"La hora {hora} para el/los médico/s de la especialidad \
{identificador} y fecha {fecha} ya está reservada.\n\
Ésta es la siguiente hora disponible: {hora_actual_str} con el/los médico/s {medicos_libres}."
                if tipo_verificacion == "especialidad"
                else f"La hora {hora} para el médico {identificador} \
y fecha {fecha} ya está reservada.\nÉsta es la siguiente hora disponible: {hora_actual_str}."
            )
            return {
                "existe_disponibilidad": False,
                "medicos_libres": list(medicos_libres),
                "horas_disponibles": [hora_actual_str],
                "mensaje": mensaje
            }

        hora_actual_dt += duracion_cita # Incrementar la hora en 20 minutos

    # Si no hay horas disponibles después de la hora solicitada, devolver mensaje final
    mensaje = (
        f"La hora {hora}, y todas las horas siguientes, para la especialidad \
{identificador} y fecha {fecha} solicitada ya están reservadas."
        if tipo_verificacion == "especialidad"
        else f"La hora {hora}, y todas las horas siguientes, para el médico \
{identificador} y fecha {fecha} solicitada ya están reservadas."
    )
    return {
        "existe_disponibilidad": False,
        "medicos_libres": [],
        "horas_disponibles": [],
        "mensaje": mensaje
    }    
    
def obtener_nuevo_id_cita() -> int:
    """
    Obtiene un nuevo ID de cita incrementando el mayor ID existente en la hoja de agenda_worksheet.
    Returns: Un nuevo ID de cita.
    """
    # Obtener todas las filas de la hoja agenda_worksheet
    all_rows = agenda_worksheet.get_all_values()
    
    # Generar un nuevo ID incrementando en 1 el mayor ID existente
    ids = [int(row[0]) for row in all_rows if row[0].isdigit()]
    if ids:
        return max(ids) + 1
    # Si no hay IDs existentes, iniciar el ID de citas en 1
    return 1 
    
# Un diccionario para almacenar el estado de las conversaciones para agendar citas
estado_conversacion = {}

def obtener_estado_conversacion(user_id: str) -> dict:
    """
    Obtiene el estado de conversación de un usuario dado su ID.

    Si el ID del usuario no existe en el diccionario de estados de conversación,
    devuelve un diccionario vacío.

    Args:
        user_id (str): El ID del usuario para el que se desea obtener el estado de conversación.

    Returns:
        dict: El estado de conversación del usuario o un diccionario vacío si no existe.
    """
    return estado_conversacion.get(user_id, {})

def actualizar_estado_conversacion(user_id: str, estado: dict) -> None:
    """
    Actualiza el estado de conversación de un usuario dado su ID.

    Args:
        user_id (str): El ID del usuario para el que se desea obtener el estado de conversación.
        estado (dict): El diccionario con el estado actualizado de la conversación del usuario.
    """
    estado_conversacion[user_id] = estado
    
def iniciar_agendar_cita(params: dict) -> str:
    '''
    Incia el proceso de agendamiento de una cita médica, ya sea por especialidad o por médico.

    Args:
        params (dict): Un diccionario con las siguientes claves:
            "tipo_agendamiento" (str): Indica si la cita se agendará por "especialidad" o por "medico".
            "identificador" (str): Nombre del médico o especialidad según el tipo de agendamiento.
            "name" (str): Nombre del paciente para el que se solicita la cita.
            "dni" (str): Identificación única del paciente (DNI o equivalente).
            "fecha" (str): Fecha solicitada para la cita en formato YYYY-MM-DD.
            "hora" (str): Hora solicitada para la cita en formato HH:MM.

    Returns:
        str: Mensaje de solicitud para completar el agendamiento, o de error.
    '''
    print(f"Entrando en la función iniciar_agendar_cita con params: {params}")
    
    # Extraer parámetros del diccionario de entrada
    tipo = params.get('tipo_agendamiento') # Tipo de agendamiento: especialidad o médico
    identificador = params.get('identificador') # Especialidad o nombre del médico, según corresponda.
    name = params.get('name') # Nombre del paciente
    dni = params.get('dni') # Identificación (DNI) del paciente.
    fecha = params.get('fecha') # Fecha solicitada para la cita.
    # La hora se redondea a múltiplos de 20 minutos para ajustarse al formato de la agenda.
    hora = redondear_a_multiplo_20_minutos(params.get('hora'))
    
    # Se verifican citas previas del usuario para la misma fecha y hora.
    citas_reservadas = [
        (row[0], row[1], row[2]) # Se obtiene la ID de la cita, el médico y la especialidad.
        for row in agenda_worksheet.get_all_values() # Se recorren todas las citas en la hoja de trabajo.
        # Filtra las citas que coinciden con el DNI del paciente, la fecha y hora, excluyendo las canceladas.
        if row[4] in dni and row[5] == fecha and row[6] == hora and row[7].lower() != 'cancelada'
    ]
	
    # Verifica si ya existen citas reservadas en ese horario
    ya_tiene_citas = bool(citas_reservadas)
    
    if ya_tiene_citas:
        # Si ya tiene una cita en la misma fecha y hora, devuelve un mensaje indicando los detalles de la cita existente.
        return {
            f"No se puede agendar una cita para la fecha {fecha}{hora} solicitadas por {name} (DNI {dni}) \
porque ya dispone de citas agendadas. A continuación se indican los detalles de las \
citas que ya tiene agendadas: {citas_reservadas}"
        }
    
    # Inicializamos los posibles conjuntos de médicos y especialidades disponibles
    medicos = set() # Conjunto para almacenar los nombres de los médicos disponibles
    especialidades = set() # Conjunto para almacenar las especialidades disponibles
    
    # Maneja el agendamiento por especialidad
    if tipo == "especialidad":
        especialidad = identificador
        # Busca los médicos disponibles para la especialidad seleccionada
        medicos = buscar_medicos_especialidades(especialidad, tipo_busqueda = "especialidad")
        
        # Si no se encuentran médicos disponibles para la especialidad, se retorna un mensaje de error
        if not medicos:
            return f"No se encontró a ningún médico para la especialidad {especialidad}."
        print(f"Nombre del/los médico/s para la especialidad {especialidad}: {medicos}")

        # Verifica la disponibilidad de la especialidad en la fecha y hora solicitadas
        print(f"Verificando disponibilidad por especialidad: {especialidad}")
        disponibilidad = verificar_disponibilidad(
            fecha = fecha,
            identificador = especialidad,
            hora = hora,
            tipo_verificacion = "especialidad"
        )
        
        # Si no hay disponibilidad, retornar mensaje de error
        if not disponibilidad['existe_disponibilidad']:
            print(f"Error en disponibilidad: {disponibilidad['mensaje']}")
            return disponibilidad['mensaje']

        # Si hay más de un médico disponible, solicitar al usuario que elija uno
        if len(disponibilidad['medicos_libres']) > 1:
            # Incializamos y guardamos el estado de conversación para recordar la selección pendiente
            estado = obtener_estado_conversacion(dni)
            estado.update({
                'dni': dni,
                'name': name,
                'medico': "",
                'especialidad': especialidad,
                'fecha': fecha,
                'hora': hora
            })
            actualizar_estado_conversacion(dni, estado)
            
            # Devuelve un mensaje solicitando al usuario que elija entre los médicos disponibles
            mensaje = f"Hay varios médicos disponibles para la especialidad {especialidad}. \
¿Cuál prefieres?\n{' / '.join(disponibilidad['medicos_libres'])}"
            return mensaje
        
        # Si solo hay un médico disponible, se selecciona automáticamente
        medico = disponibilidad['medicos_libres'][0]
        
    # Maneja el agendamiento por médico
    elif tipo == "medico":
        medico = identificador
        # Busca las especialidades que ofrece el médico seleccionado
        especialidades = buscar_medicos_especialidades(medico, tipo_busqueda = "medico")
        if not especialidades:
            return f"No se encontró una especialidad para el médico {medico}."
        print(f"Nombre de la/s especialidad/es para el médico {medico}: {especialidades}")

        # Verifica la disponibilidad del médico en la fecha y hora solicitadas
        print(f"Verificando disponibilidad por médico: {medico}")
        disponibilidad = verificar_disponibilidad(
            fecha = fecha,
            identificador = medico,
            hora = hora,
            tipo_verificacion = "medico"
        )
        
        # Si no hay disponibilidad, devuelve un mensaje de error
        if not disponibilidad['existe_disponibilidad']:
            print(f"Error en disponibilidad: {disponibilidad['mensaje']}")
            return disponibilidad['mensaje']

        # Si el médico tiene más de una especialidad, solicita al paciente que elija una
        if len(especialidades) > 1:
            # Actualiza el estado de la conversación para recordar la selección pendiente
            estado = obtener_estado_conversacion(dni)
            estado.update({
                'dni': dni,
                'name': name,
                'medico': medico,
                'especialidad': "",
                'fecha': fecha,
                'hora': hora
            })
            actualizar_estado_conversacion(dni, estado)
            
            # Devuelve un mensaje solicitando al usuario que elija entre las especialidades disponibles
            mensaje = f"Hay varias especialidad disponibles para el/la {medico}. \
¿Cuál prefieres?\n{' / '.join(especialidades)}"
            return mensaje
            
        # Si solo hay una especialidad disponible, se selecciona automáticamente
        especialidad = especialidades[0]

    # Genera un nuevo ID para la cita
    cita_id = obtener_nuevo_id_cita()
    print(f"Nuevo ID de cita: {cita_id}")

    # Agregar la cita a la hoja agenda_worksheet
    first_empty_row = len(agenda_worksheet.get_all_values()) + 1
    
    # Crea una lista con los detalles de la cita para agregarla a la agenda
    cita_data = [
        [cita_id, medico, especialidad, name,
        dni, fecha, hora, 'Programada',
        datetime.now().strftime('%Y-%m-%d %H:%M:%S')]
    ]
    print(f"Cita a agendar: {cita_data}")

    # Actualiza los datos en bloque en la hoja de agenda
    agenda_worksheet.update(
        f'A{first_empty_row}:I{first_empty_row}', # Rango donde se actualizarán los datos
        cita_data,
        value_input_option='USER_ENTERED' # Permite la entrada de datos por el usuario
    )
    
    # Devuelve un mensaje de éxito al agendar la cita
    result_message = f"Cita agendada con éxito con el médico {medico} \
    en la especialidad {especialidad} el {fecha} a las {hora}."
    print(result_message)
    return result_message
    
def completar_agendar_cita(params: dict) -> str:
    '''
    Completa el proceso de agendar una cita después de la selección de
    médico o especialidad por parte del usuario.

    Args:
        params (dict): Un diccionario con las siguientes claves:
            dni (str): Identificador del usuario (DNI).
            seleccion (str): Selección del usuario (médico o especialidad).

    Returns:
        str: Mensaje de confirmación o error.
    '''
    print(f"Entrando en la función completar_agendar_cita con params: {params}")
    
    # Obtener todas las filas de la hoja medico_worksheet para validar opciones
    all_rows = medico_worksheet.get_all_values()

    # Recuperar el estado de la conversación sobre la agendamiento de cita
    estado = obtener_estado_conversacion(params.get('dni'))
    dni = estado.get('dni')
    name = estado.get('name')
    medico = estado.get('medico')
    especialidad = estado.get('especialidad')
    fecha = estado.get('fecha')
    hora = estado.get('hora')
    
    # Si no se ha seleccionado un médico, obtenemos la selección del usuario
    if not medico:
        medico = params.get('seleccion') # Obtener el médico seleccionado por el usuario
        # Crear un conjunto de médicos disponibles desde la hoja
        medicos = {row[1] for row in all_rows}
        # Validar que el médico seleccionado sea uno de los médicos disponibles
        if medico not in medicos:
            return "Error: Selección no válida. Vuelve a indicar el médico deseado."
            
    # Si no se ha seleccionado una especialidad, obtenemos la selección del usuario
    if not especialidad:
        especialidad = params.get('seleccion') # Obtener la especialidad seleccionada por el usuario
        # Crear un conjunto de especialidades disponibles desde la hoja
        especialidades = {row[0] for row in all_rows}
        # Validar que la especialidad seleccionada sea una de las especialidades disponibles
        if especialidad not in especialidades:
            return "Error: Selección no válida. Vuelve a indicar la especialidad deseada."

    # Obtener un nuevo ID para la cita
    cita_id = obtener_nuevo_id_cita()
    print(f"Nuevo ID de cita: {cita_id}")

    # Agregar la cita a la hoja agenda_worksheet
    first_empty_row = len(agenda_worksheet.get_all_values()) + 1
    
    # Crear una lista con los datos de la cita a agendar
    cita_data = [
        [cita_id, medico, especialidad, name,
        dni, fecha, hora, 'Programada',
        datetime.now().strftime('%Y-%m-%d %H:%M:%S')]
    ]
    print(f"Cita a agendar: {cita_data}")

    # Actualiza los datos en bloque en la hoja de agenda
    agenda_worksheet.update(
        f'A{first_empty_row}:I{first_empty_row}',
        cita_data,
        value_input_option='USER_ENTERED'
    )
    
    # Mensaje de éxito al agendar la cita
    result_message = f"Cita agendada con éxito con el médico {medico} \
en la especialidad {especialidad} el {fecha} a las {hora}."
    print(result_message)
    return result_message    
    
def consultar_disponibilidad(
    params: dict
)-> Dict[str, Union[
    bool,
    dict[str, Union[
        list[str],
        list[str]
    ]],
    str
]]:
    '''
    Consulta las fechas y horas disponibles para una especialidad
    o médico en un rango de fechas específico.

    Args:
        params (dict): Diccionario que debe contener los siguientes campos:
            "tipo_consulta" (str): Indica 'especialidad' si se especifica una especialidad médica,
                o 'médico' si se proporciona el nombre de un médico.
            "identificador" (str): Dependiendo del tipo de consulta, especifica la
                especialidad médica o el nombre del médico.
            "fecha_inicio" (str): Fecha de inicio del rango en formato YYYY-MM-DD.
                Ejemplo: "2024-06-01".
            "fecha_fin" (str, opcional): Fecha de fin del rango en formato YYYY-MM-DD.
                Si no se proporciona, se considera igual a la fecha de inicio.

    Returns:
        Dict: Un dicionario con las siguientes claves:
            "exito_consulta" (bool): Indica si la consulta fue exitosa y existe disponibilidad.
            "disponibilidades" (dict): Otro diccionario con las sigueintes claves:
                "fecha" (dict): Fecha en formato YYYY-MM-DD:
                    "horas_disponibles" (List[str]): Listado con las horas disponibles,
                        en formato HH:MM.
                    "medicos_libres" (List[str]): Conjunto de médicos con disponibilidad
                    en la fecha indicada.
            "mensaje" (str): Mensaje de error o informativo.
    '''
    print(f"Entrando en la función consultar_disponibilidad con params: {params}")

    # Validación de parámetros obligatorios
    tipo_consulta = params.get('tipo_consulta')
    identificador = params.get('identificador') # Puede ser especialidad o nombre del médico
    fecha_inicio = params.get('fecha_inicio') # Fecha de inicio del rango
    fecha_fin = params.get('fecha_fin') # Fecha de fin del rango (opcional)
    
    # Comprobar que los parámetros obligatorios están presentes
    if not tipo_consulta or not identificador or not fecha_inicio:
        return {
            "exito_consulta": False,
            "disponibilidades": {},
            "mensaje": "Faltan parámetros obligatorios: \
'tipo_consulta', 'identificador' o 'fecha_inicio'."
        }

    # Validación y conversión de fechas
    try:
        fecha_inicio_dt = datetime.strptime(fecha_inicio, '%Y-%m-%d')
        # Si fecha_fin no se proporciona, asignar fecha_fin igual a fecha_inicio
        if fecha_fin:
            fecha_fin_dt = datetime.strptime(fecha_fin, '%Y-%m-%d')
        else:
            fecha_fin_dt = fecha_inicio_dt
    except ValueError as e:
        # Manejar errores de formato de fecha
        return {
            "exito_consulta": False,
            "disponibilidades": {},
            "mensaje": f"Formato de fecha inválido: {str(e)}"
        }

    # Verificación de que la fecha de inicio no sea posterior a la fecha de fin
    if fecha_inicio_dt > fecha_fin_dt:
        return {
            "exito_consulta": False,
            "disponibilidades": {},
            "mensaje": "La fecha de inicio no puede ser posterior a la fecha de fin."
        }

    # Inicialización de la estructura para almacenar las disponibilidades
    disponibilidades = {}
    fecha_actual_dt = fecha_inicio_dt # Iniciar desde la fecha de inicio

    # Consulta de disponibilidad por fecha
    while fecha_actual_dt <= fecha_fin_dt:
        fecha_actual_str = fecha_actual_dt.strftime('%Y-%m-%d')

        # Llamada a la función que verifica la disponibilidad para una fecha específica
        disponibilidad = verificar_disponibilidad(
            fecha = fecha_actual_str,
            identificador = identificador,
            hora = None, # No se especifica hora para obtener disponibilidad general
            tipo_verificacion = tipo_consulta
        )

        if disponibilidad['existe_disponibilidad']:
            # Si hay disponibilidad, almacenar horas y médicos libres
            disponibilidades[fecha_actual_str] = {
                "horas_disponibles": disponibilidad['horas_disponibles'],
                "medicos_libres": disponibilidad['medicos_libres']
            }
        else:
            # Mostrar mensaje de error si no hay disponibilidad en la fecha actual
            print(disponibilidad['mensaje'])
         
        # Avanzar a la siguiente fecha
        fecha_actual_dt += timedelta(days=1)
        
    # Verificar si se encontraron disponibilidades
    if disponibilidades:
        return {
            "exito_consulta": True,
            "disponibilidades": disponibilidades,
            "mensaje": "Existe disponibilidad."
        }

    return {
        "exito_consulta": False,
        "disponibilidades": {},
        "mensaje": "No hay disponibilidad para ningún día en las fechas solicitadas."
    }    
    
def buscar_paciente(dni: str) -> tuple[bool, str]:
    '''
    Busca un paciente por su DNI.

    Args:
        dni (str): El DNI del paciente a buscar.

    Returns:
        tuple[bool, str]: Un tuple donde el primer valor es un booleano que indica si 
                            el paciente fue encontrado (True) o no (False), y el segundo 
                            valor es el nombre del paciente si fue encontrado, o una 
                            cadena vacía si no.
    '''
    # Obtener todas las filas de la hoja de cálculo que contiene la agenda
    all_rows = agenda_worksheet.get_all_values()
    
    # Iterar sobre cada fila para buscar el DNI del paciente
    for row in all_rows:
        # Comprobar si el DNI de la fila actual coincide con el DNI buscado
        if row[4] == dni:
            # Retornar True y el nombre del paciente si se encuentra
            return True, row[3] # row[3] contiene el nombre del paciente
    
    # Retornar False y una cadena vacía si el paciente no se encuentra
    return False, ""

# Un diccionario para almacenar el estado de las cancelaciones de citas
estado_cancelacion = {}    
    
def obtener_estado_cancelacion(user_id: str) -> List[str]:
    """
    Obtiene el estado de la cancelación de un usuario dado su ID.

    Si el ID del usuario no existe en el diccionario de estados de cancelación,
    devuelve un diccionario vacío.

    Args:
        user_id (str): El ID del usuario para el que se desea obtener el estado de cancelación.

    Returns:
        list: Valores de la cita (row) de la que se quiere confirmar cancelación,
            o una lista vacía si todavía no está definida para el user_id.
    """
    return estado_cancelacion.get(user_id, [])

def actualizar_estado_cancelacion(user_id: str, cita: List[str]) -> None:
    """
    Actualiza el estado de cancelación de un usuario dado su ID.

    Args:
        user_id (str): El ID del usuario para el que se desea obtener el estado de cancelación.
        cita (list): Valores de la cita (row) de la que se quiere confirmar cancelación.
    """
    estado_cancelacion[user_id] = cita
    
def buscar_cita_a_cancelar(params: dict) -> Dict[str, Union[bool, str]]:
    '''
    Solicita la cancelación de una cita agendada del usuario. Requiere confirmación.

    Args:
        params (dict): Diccionario que debe contener los siguientes campos:
            "dni": Indica el DNI del paciente.
            "cita_id" (int, opcional): Indica el número de identificación de la cita.
            "fecha" (str, opcional): Indica la fecha de la cita, en formato YYYY-MM-DD.
            "hora" (str, opcional): Indica la hora de la cita, en formato HH:MM.

    Returns:
        Dict: Un diccionario con las siguientes claves:
            "cita_cancelada" (bool): Indica si la cita fue cancelada o no.
            "mensaje_cancelacion" (str): Mensaje de error o informativo.
    '''
    print(f"Entrando en la función buscar_cita_a_cancelar con params: {params}")
    
    # Obtener el ID de la cita, DNI del paciente, fecha y hora de los parámetros
    cita_id = params.get('cita_id')
    dni = params.get('dni')
    fecha = params.get('fecha')
    hora = params.get('hora')
    
    # Validar que se haya proporcionado el DNI
    if not dni:
        return {
            'cita_cancelada': False,
            'mensaje_cancelacion': "DNI no proporcionado." # Mensaje de error si no se proporciona el DNI
        }

    # Buscar el nombre del paciente utilizando su DNI
    paciente_encontrado, nombre_paciente = buscar_paciente(dni)
    if not paciente_encontrado:
        return {
            'cita_cancelada': False,
            'mensaje_cancelacion': f"No se encontró a ningún paciente con el DNI {dni}."
        }

    # Obtener todas las citas que no han sido canceladas de la hoja agenda_worksheet
    all_rows = agenda_worksheet.get_all_values()
    rows_not_cancelled = [row for row in all_rows if row[7].lower() != 'cancelada']

    cita = None # Inicializar la variable que almacenará la cita encontrada

    # Intentar cancelar la cita utilizando el ID proporcionado
    if cita_id:
        for row in rows_not_cancelled:
            if row[0] == str(cita_id) and row[4] == dni: # Coincidir con el ID de la cita y el DNI del paciente
                cita = row # Asignar la cita encontrada a la variable
                break
        # Mensaje en caso de que no se encuentre la cita por ID
        resultado_no_hay_cita = {
            'cita_cancelada': False,
            'mensaje_cancelacion': f"No se encontró la cita {cita_id} \
a nombre de {nombre_paciente} (DNI {dni})."
        }
    else:
        # Si no se proporciona cita_id, se debe proporcionar fecha y hora
        if not (fecha and hora):
            return {
                'cita_cancelada': False,
                'mensaje_cancelacion': "Si no se proporciona 'cita_id' \
se debe proporcionar 'fecha' y 'hora', o viceversa." # Mensaje si faltan parámetros
            }
        
        # Buscar la cita utilizando fecha y hora
        for row in rows_not_cancelled:
            if row[4] == dni and row[5] == fecha and row[6] == hora: # Coincidir con el DNI, fecha y hora
                cita = row # Asignar la cita encontrada a la variable
                break
        # Mensaje en caso de que no se encuentre la cita por fecha y hora
        resultado_no_hay_cita = {
            'cita_cancelada': False,
            'mensaje_cancelacion': f"No se encontró la cita de {nombre_paciente} (DNI {dni}) \
para el {fecha} a las {hora}."
        }
    
    # Si se encontró la cita, solicitar confirmación para la cancelación
    if cita:
        # Actualizar el estado de cancelación en el sistema
        actualizar_estado_cancelacion(dni, {'row': cita})
        return {
            'cita_cancelada': False, # Aún no se ha cancelado la cita, se está solicitando confirmación
            'mensaje_cancelacion': f"¿Seguro que deseas cancelar la Cita de \
{cita[3]} (DNI {cita[4]}) con ID {cita[0]}, programada para el {cita[5]} a las {cita[6]} \
con el médico {cita[1]} (Especialidad: {cita[2]}?" 
        }
    
    # Retornar mensaje de error si no se encontró ninguna cita
    return resultado_no_hay_cita

def confirmar_cita_a_cancelar(params: dict) -> Dict[str, Union[bool, str]]:
    """
    Confirma la cancelación de una cita según la elección del usuario.

    Args:
        params (dict): Un diccionario con la siguiente clave:
            "dni" (str): Identificador del usuario (DNI). 
            "confirmacion" (str): Confirmación del Usuario ("SI" o "NO").

    Returns:
        Returns:
            Dict: Un diccionario con las siguientes claves:
                "cita_cancelada" (bool): Indica si la cita fue cancelada o no..
                "mensaje_cancelacion" (str): Mensaje informativo.
    """
    print(f"Entrando en la función confirmar_cita_a_cancelar con params: {params}")
    
    # Obtener el DNI y la elección de confirmación de los parámetros
    dni = params.get('dni')
    eleccion = params.get('confirmacion')
    
    # Validar que se hayan proporcionado el DNI y la elección
    if not dni or not eleccion:
        return {
            'cita_cancelada': False,
            'mensaje_cancelacion': "DNI y elección de confirmación son requeridos."
        }

    # Recuperar la cita de la que se quiere confirmar la cancelación
    cita = obtener_estado_cancelacion(dni)
    
    # Verificar si se encontró una cita pendiente de confirmación
    if not cita:
        return {
            'cita_cancelada': False,
            'mensaje_cancelacion': f"No hay una cita pendiente de confirmación para el DNI {dni}."
        }

    row = cita.get('row') # Obtener la fila de la cita
    
    # Comprobar si la fila de la cita es válida
    if not row:
        return {
            'cita_cancelada': False,
            'mensaje_cancelacion': "No se encontró información de la cita para confirmar."
        }

    # Desempaquetar la información relevante de la fila
    cita_id = row[0]
    medico = row[1]
    especialidad = row[2]
    nombre_paciente = row[3]
    dni = row[4]
    fecha = row[5]
    hora = row[6]
    
    # Procesar la elección del usuario
    if eleccion.upper() == 'SI':  # Si el usuario confirma la cancelación
        # Obtener todas las citas de la hoja agenda_worksheet
        all_rows = agenda_worksheet.get_all_values()
        # Encontrar la fila original en la hoja de cálculo completa
        original_row = all_rows.index(row) + 1
        # Cancelar la cita actualizando el estado en la hoja de cálculo
        agenda_worksheet.update_cell(original_row, 8, 'Cancelada')
        return {
            'cita_cancelada': True,
            'mensaje_cancelación': f"Cita de {nombre_paciente} (DNI {dni}) \
con ID {cita_id}, programada para el {fecha} a las {row[6]} con el médico {medico} \
(Especialidad: {especialidad}) CANCELADA con éxito."
        }

    # Si el usuario no confirma la cancelación
    return {
        'cita_cancelada': False, # Indicar que la cita no ha sido cancelada
        'mensaje_cancelación': f"Cancelación de cita de {nombre_paciente} \
(DNI {dni}) con ID {cita_id}, programada para el {fecha} a las {hora} \
con el médico {medico} (Especialidad: {especialidad}) NO confirmada."
    }

def formatear_cita(cita):
    """
    Función auxiliar que toma un diccionario de cita y lo formatea como una cadena.
    """
    return (
        f"\tCita ID: {cita['cita_id']}\n"
        f"\tMédico: {cita['medico']}\n"
        f"\tEspecialidad: {cita['especialidad']}\n"
        f"\tFecha: {cita['fecha']}\n"
        f"\tHora: {cita['hora']}\n"
    )

def consultar_citas_agendadas(params):
    '''
    Consulta las citas agendadas para un usuario en un periodo específico.

    Args:
        params (dict): Diccionario que debe contener los siguientes campos:
            "dni": Indica el DNI del paciente (obligatorio).
            "fecha_inicio": Fecha de inicio del periodo en formato YYYY-MM-DD (opcional).
            "fecha_fin": Fecha de fin del periodo en formato YYYY-MM-DD (opcional).
            "hora" (str, opcional): Indica la hora de la cita, en formato HH:MM.

    Returns:
        Mensaje con las citas encontradas o un mensaje de error.
    '''
    print(f"Entrando en la función consultar_citas_agendadas con params: {params}")
    
    # Extraer parámetros
    dni = params.get('dni')
    fecha_inicio = params.get('fecha_inicio')
    fecha_fin = params.get('fecha_fin')
    
    # Verifica que se proporcione el DNI, que es obligatorio
    if not dni:
        return "El DNI del paciente es obligatorio."

    try:
        # Intenta convertir las fechas de inicio y fin a objetos datetime
        fecha_inicio_dt = datetime.strptime(fecha_inicio, '%Y-%m-%d') if fecha_inicio else None
        fecha_fin_dt = datetime.strptime(fecha_fin, '%Y-%m-%d') if fecha_fin else None
    except ValueError as e:
        # Si hay un error en el formato de la fecha, retorna un mensaje de error
        return f"Formato de fecha inválido: {e}"

    # Si no se proporciona fecha_fin, se usa fecha_inicio como fecha_fin
    if fecha_inicio_dt and not fecha_fin_dt:
        fecha_fin_dt = fecha_inicio_dt
    
    # Verifica que la fecha de inicio no sea posterior a la fecha de fin
    if fecha_inicio_dt and fecha_fin_dt and fecha_inicio_dt > fecha_fin_dt:
        return "La fecha de inicio no puede ser posterior a la fecha de fin."

    # Obtener todas las filas de la hoja agenda_worksheet
    all_rows = agenda_worksheet.get_all_values()
    # Filtrar las citas que no están canceladas
    rows_not_cancelled = [row for row in all_rows if row[7].lower() != 'cancelada']
    
    # Inicializa una lista para almacenar las citas encontradas
    citas = []
    for row in rows_not_cancelled:
        # Comprobar si el DNI del paciente coincide con el de la cita
        if row[4] == dni:
            fecha_cita = datetime.strptime(row[5], '%Y-%m-%d')
            # Verificar si la fecha de la cita está dentro del rango especificado
            if ((fecha_inicio_dt is None or fecha_cita >= fecha_inicio_dt) and
                (fecha_fin_dt is None or fecha_cita <= fecha_fin_dt)):
                # Añadir la cita a la lista de citas encontradas
                citas.append({
                    'cita_id': row[0],
                    'medico': row[1],
                    'especialidad': row[2],
                    'fecha': row[5],
                    'hora': row[6]
                })
                
    # Si se encontraron citas, formatearlas y retornarlas
    if citas:
        citas_str = "\n".join(formatear_cita(cita) for cita in citas)
        return f"Tus citas agendadas:\n{citas_str}"
        
    # Si no se encontraron citas, retornar un mensaje adecuado
    return "No se encontraron citas para el DNI proporcionado en el periodo especificado."
    
        
# Un diccionario para almacenar el estado de las modificaciones de citas
estado_modificacion = {}    
    
def obtener_estado_modificacion(user_id: str) -> List[str]:
    """
    Obtiene el estado de la modificación de un usuario dado su ID.

    Si el ID del usuario no existe en el diccionario de estados de modificación,
    devuelve un diccionario vacío.

    Args:
        user_id (str): El ID del usuario para el que se desea obtener el estado de modificación.

    Returns:
        list: Valores de la cita (row) de la que se quiere confirmar la modificación,
            o una lista vacía si todavía no está definida para el user_id.
    """
    return estado_modificacion.get(user_id, [])

def actualizar_estado_modificacion(user_id: str, cita: List[str]) -> None:
    """
    Actualiza el estado de modificación de un usuario dado su ID.

    Args:
        user_id (str): El ID del usuario para el que se desea obtener el estado de modificación.
        cita (list): Valores de la cita (row) de la que se quiere confirmar la modificación.
    """
    estado_modificacion[user_id] = cita       
    
def iniciar_modificar_cita(params: dict) -> Dict[str, Union[bool, List[str], str]]:
    '''
    Inicia el proceso para modificar una cita médica.
    
    Valida la existencia del paciente y la cita original, y verifica las nuevas fechas y horas disponibles.
    Si la cita existe, busca opciones de horarios disponibles para la nueva fecha.

    Args:
        params (dict): Un diccionario con las siguientes claves:
            "name" (str): Nombre del paciente.
            "dni" (str): Identificación del paciente.
            "cita_id" (str, opcional): ID de la cita que se desea modificar.
            "fecha" (str): Fecha original de la cita en formato YYYY-MM-DD.
            "hora" (str): Hora original de la cita en formato HH:MM.
            "fecha_nueva" (str): Nueva fecha para la cita en formato YYYY-MM-DD.
            "hora_nueva" (str): Nueva hora para la cita en formato HH:MM.
    Returns:
        dict: Un diccionario con:
            - "cita_modificar" (bool): Indica si se puede continuar con la modificación.
            - "horas_disponibles" (list): Horarios disponibles para la nueva cita.
            - "mensaje_modificar" (str): Mensaje de confirmación o error.
    '''
    print(f"Entrando en la función iniciar_modificar_cita con params: {params}")
    
    # Extraer parámetros del diccionario de entrada
    name = params.get('name') # Nombre del paciente
    dni = params.get('dni') # DNI del paciente
    cita_id = params.get('cita_id') # ID de la cita (opcional)
    fecha = params.get('fecha') # Fecha de la cita
    # La hora se redondea a múltiplos de 20 minutos para ajustarse al formato de la agenda
    hora = params.get('hora')
    if hora:
        hora = redondear_a_multiplo_20_minutos(hora)
    fecha_nueva = params.get('fecha_nueva') # Nueva fecha para la cita
    # Redondear la nueva hora solicitada a un múltiplo de 20 minutos
    hora_nueva = params.get('hora_nueva')
    if hora_nueva:
        hora_nueva = redondear_a_multiplo_20_minutos(hora_nueva)

    # Validar que se haya proporcionado el DNI
    if not dni:
        return {
            "cita_modificar": False,
            "horas_disponibles": [],
            "mensaje_modificar": "DNI no proporcionado."
        }

    # Verificar si el paciente existe en el sistema utilizando su DNI
    paciente_encontrado, nombre_paciente = buscar_paciente(dni)
    if not paciente_encontrado:
        # Si el paciente no existe, se retorna un mensaje de error
        return {
            "cita_modificar": False,
            "horas_disponibles": [],
            "mensaje_modificar": f"No se encontró a ningún paciente con el DNI {dni}."
        } 

    # Obtener todas las citas no canceladas de la hoja agenda_worksheet
    all_rows = agenda_worksheet.get_all_values()
    rows_not_cancelled = [row for row in all_rows if row[7].lower() != 'cancelada']

    cita = None # Inicializar la variable para almacenar la cita encontrada
    
    # Búsqueda de la cita por ID (si se proporciona)
    if cita_id:
        # Iterar sobre todas las citas no canceladas para encontrar una coincidencia con el ID y el DNI
        for row in rows_not_cancelled:
            if row[0] == str(cita_id) and row[4] == dni:
                cita = row # Guardar la cita encontrada
                break # Salir del bucle, ya que la cita se encontró
        # Si no se encontró una cita con el ID proporcionado, devolver un mensaje de error
        
        if not cita:
            return {
                "cita_modificar": False,
                "horas_disponibles": [],
                "mensaje_modificar": f"No se encontró la cita {cita_id} \
    a nombre de {nombre_paciente} (DNI {dni})."
            }
        
    else:
        # Si no se proporciona un ID de cita, se requiere la fecha y la hora originales de la cita
        if not (fecha and hora):
            # Si faltan la fecha o la hora, devolver un mensaje de error
            return {
                "cita_modificar": False,
                "horas_disponibles": [],
                "mensaje_modificar": "Si no se proporciona 'cita_id' \
se debe proporcionar 'fecha' y 'hora', o viceversa." 
            }
        
        # Buscar la cita por fecha y hora si no se ha proporcionado un ID
        for row in rows_not_cancelled:
            if row[4] == dni and row[5] == fecha and row[6] == hora: # Coincidir con el DNI, fecha y hora
                cita = row # Guardar la cita encontrada
                break # Salir del bucle, ya que la cita se encontró
                
        # Si no se encontró una cita con la fecha y hora proporcionadas, devolver un mensaje de error
        resultado_no_hay_cita = {
            "cita_modificar": False,
            "horas_disponibles": [],
            "mensaje_modificar": f"No se encontró la cita de {nombre_paciente} (DNI {dni}) \
para el {fecha} a las {hora}."
        }
    
    # Si se encontró la cita original, proceder con la modificación
    if cita:
        actualizar_estado_modificacion(dni, {'row': cita}) # Marcar la cita para modificación
        
        # Definir el rango de atención: de 8:00 AM a 7:00 PM con citas de 20 minutos
        hora_inicio_dt = time(8, 0)  
        hora_fin_dt = time(19, 0)   
        duracion_cita = timedelta(minutes=20) 
        
        # Obtener todas las citas reservadas del mismo médico, especialidad y fecha
        citas_reservadas = [
        (row[1], row[2], row[5], row[6]) # (Médico, especialidad, fecha, hora)
        for row in agenda_worksheet.get_all_values() 
        if row[1] in cita[1] and row[2] == cita[2] and row[5] == fecha_nueva and row[7].lower() != 'cancelada' 
        ]
        
        # Si no se proporciona una hora nueva, devolver todas las horas disponibles para la fecha
        if not hora_nueva:
            horas_disponibles = [] # Lista para almacenar las horas disponibles

            # Empezar a verificar desde las 8:00 AM
            hora_actual_dt = datetime.combine(datetime.strptime(fecha_nueva, '%Y-%m-%d'), hora_inicio_dt)
            
            # Iterar desde la hora de inicio hasta la hora de cierre, incrementando cada 20 minutos
            while hora_actual_dt.time() < hora_fin_dt:
                hora_actual_str = hora_actual_dt.strftime('%H:%M') # Formatear la hora actual como string
                # Verificar si el médico está disponible en esa hora
                if (cita[1], cita[2], cita[5], cita[6]) not in citas_reservadas:
                    if hora_actual_str not in horas_disponibles:
                        horas_disponibles.append(hora_actual_str) # Añadir la hora disponible
                hora_actual_dt += duracion_cita # Incrementar la hora en 20 minutos
                
            # Si hay horas disponibles, devolver la lista
            if horas_disponibles:
                return {
                    "cita_modificar": False,
                    "horas_disponibles": list(horas_disponibles),
                    "mensaje": f"Necesito le des al usuario los datos completos de su cita inicial \
cita  de {cita[3]} (DNI {cita[4]}) \ con ID {cita[0]}, programada para el {cita[5]} \
a las {cita[6]} con el médico {cita[1]} (Especialidad: {cita[2]}) y le indiques los horarios \
disponibles, solicitándole especificar cuá prefiere para modificar su cita: {horas_disponibles}. Por favor, \
si hay muchas horas disponibles dáselo de una mejor forma, no como un listado en vertical."
                }
                
            # Si no hay horarios disponibles
            return {
                "cita_modificar": False,
                "horas_disponibles": [],
                "mensaje": f"Para la fecha {fecha} no hay horarios disponibles."
            }

        # Si se especifica una hora, verificar la disponibilidad en esa hora
        hora_redondeada = redondear_a_multiplo_20_minutos(hora_nueva) # Redondear la hora solicitada
        hora_actual_redondeada_dt = datetime.strptime(hora_redondeada, '%H:%M').time()

        # Verificar si la hora está dentro del horario de atención
        if not hora_inicio_dt <= hora_actual_redondeada_dt < hora_fin_dt:
            return {
                "cita_modificar": False,
                "horas_disponibles": [],
                "mensaje": "Hora no válida. Por favor elige una hora dentro del horario de atención."
            }
           
        # Verificar si ya existe una cita en la hora especificada
        existe_cita_con_hora = any(cita[3] == hora_redondeada for cita in citas_reservadas)
        
        # Si la hora es válida y está disponible, devolver el mensaje de éxito
        if not existe_cita_con_hora:
            return {
                "cita_modificar": True,
                "horas_disponibles": hora_redondeada,
                "mensaje": f"Necesito le des al usuario los datos completos de su cita inicial \
cita  de {cita[3]} (DNI {cita[4]}) \ con ID {cita[0]}, programada para el {cita[5]} \
a las {cita[6]} con el médico {cita[1]} (Especialidad: {cita[2]}) y le solicites confirmar \
si está seguro de querer modificar a la hora que ha solicitado {hora_nueva} de la fecha {fecha_nueva}."
            }
       
        # Si la hora está ocupada, buscar la siguiente hora disponible en el día
        fecha_actual_dt = datetime.strptime(fecha_nueva, '%Y-%m-%d')
        hora_actual_dt = datetime.combine(fecha_actual_dt, hora_actual_redondeada_dt) + duracion_cita    
        
        # Continuar buscando horas disponibles hasta el cierre de la clínica
        while hora_actual_dt.time() < hora_fin_dt:
            hora_actual_str = hora_actual_dt.strftime('%H:%M')
            existe_cita_con_hora = any(cita[3] == hora_actual_str for cita in citas_reservadas)
            # Si se encuentra una hora disponible, devolver True e indicar la siguiente hora libre
            if not existe_cita_con_hora:
                return {
                    "cita_modificar": False,
                    "horas_disponibles": hora_actual_str,
                    "mensaje": f"Necesito le des al usuario los datos completos de su cita inicial \
cita  de {cita[3]} (DNI {cita[4]}) \ con ID {cita[0]}, programada para el {cita[5]} \
a las {cita[6]} con el médico {cita[1]} (Especialidad: {cita[2]}) y le indiques que la hora {hora_nueva} \
y fecha {fecha_nueva} ya está reservada.  \n\
Informa que la siguiente hora disponible: {hora_actual_str}. Y solicita confirmar si desea continuar con \
la modificación."
            }
        hora_actual_dt += duracion_cita # Incrementar la hora en 20 minutos
        
    # Si no hay horas disponibles, devolver False
    return {
        "cita_modificar": False,
        "horas_disponibles": [],
        "mensaje": f"La hora {hora_nueva}, y todas las horas siguientes, para el médico {cita[0]} de la especialidad {cita[1]} \
y fecha {fecha_nueva} solicitada ya están reservadas."
    }
    
    
def confirmar_modificar_cita(params: dict) -> Dict[str, Union[bool, str]]:
    """
    Confirma la modificación de una cita según la elección del usuario.

    Args:
        params (dict): Un diccionario con la siguiente clave:
            "dni" (str): Identificador del usuario (DNI). 
            "confirmacion" (str): Confirmación del Usuario ("SI" o "NO").
            "fecha_nueva" (str): Fecha nueva de la cita en formato YYYY-MM-DD.
            "hora_nueva" (str): Hora nueva de la cita en formato HH:MM.

    Returns:
        Returns:
            Dict: Un diccionario con las siguientes claves:
                "cita_modificada" (bool): Indica si la cita fue modificada o no..
                "mensaje_modificacion" (str): Mensaje informativo.
    """
    print(f"Entrando en la función confirmar_modificar_cita con params: {params}")
    
    # Obtener el DNI y la elección de confirmación de los parámetros
    dni = params.get('dni')
    eleccion = params.get('confirmacion')
    fecha_nueva = params.get('fecha_nueva')
    hora_nueva = params.get('hora_nueva')
    
    # Validar que se hayan proporcionado el DNI y la elección
    if not dni or not eleccion or not fecha_nueva or not hora_nueva:
        return {
            "cita_modificada": False,
            "mensaje_modificacion": "DNI, elección de confirmación, fecha y hora a la que hay que modificar son requeridos."
        }
    
    # Recuperar la cita de la que se quiere confirmar la cancelación
    cita = obtener_estado_modificacion(dni)
    
    # Verificar si se encontró una cita pendiente de confirmación
    if not cita:
        return {
            "cita_modificada": False,
            "mensaje_modificacion": f"No hay una cita pendiente de confirmación para el DNI {dni}."
        }
    
    row = cita.get('row') # Obtener la fila de la cita
    
    # Comprobar si la fila de la cita es válida
    if not row:
        return {
            'cita_modificada': False,
            'mensaje_modificacion': "No se encontró información de la cita para confirmar."
        }
    
    # Desempaquetar la información relevante de la fila
    cita_id = row[0]
    medico = row[1]
    especialidad = row[2]
    nombre_paciente = row[3]
    dni = row[4]
    fecha = row[5]
    hora = row[6]    
    
    # Procesar la elección del usuario
    if eleccion.upper() == 'SI':  # Si el usuario confirma la cancelación
        # Obtener todas las citas de la hoja agenda_worksheet
        all_rows = agenda_worksheet.get_all_values()
        # Encontrar la fila original en la hoja de cálculo completa
        original_row = all_rows.index(row) + 1
        # Modicar la cita actualizando el estado en la hoja de cálculo
        agenda_worksheet.update_cell(original_row, 6, fecha_nueva)
        agenda_worksheet.update_cell(original_row, 7, hora_nueva)
        agenda_worksheet.update_cell(original_row, 8, 'Reprogramada')
        agenda_worksheet.update_cell(original_row, 9, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        return {
            'cita_modificada': True,
            'mensaje_modificacion': f"Cita de {nombre_paciente} (DNI {dni}) \
con ID {cita_id} con el médico {medico} (Especialidad: {especialidad}) y \
 {fecha} {row[6]} es MODIFICADA con éxito a {fecha_nueva}{hora_nueva}   "
        }
    
    # Si el usuario no confirma la modificación
    return {
        'cita_modificada': False, # Indicar que la cita no ha sido modificada
        'mensaje_modificacion': f"Modificación de cita de {nombre_paciente} \
        (DNI {dni}) con ID {cita_id} y  {fecha} a las {hora} \
        con el médico {medico} (Especialidad: {especialidad}) NO modificada."
    }   

def wait_on_run(run, thread):
    '''
    Espera a que una ejecución (run) pase de estar en cola o en progreso a un estado final.

    Args:
        run (object): Objeto que representa la ejecución (run) con atributos:
            - status (str): El estado actual de la ejecución.
                Puede ser "queued", "in_progress" u otro estado final.
            - id (str): Identificador único del run.
        thread (object): Objeto que representa el hilo (thread) en el que se ejecuta el run,
        con los siguientes atributos:
            - id (str): Identificador único del thread.

    Returns:
        object: El objeto de la ejecución (run) actualizado con su estado final.
    '''
    # Mientras el estado de la ejecución sea "queued" o "in_progress", se sigue consultando su estado
    while run.status in {"queued", "in_progress"}:
        # Actualiza el objeto run con la información más reciente desde el cliente
        run = client.beta.threads.runs.retrieve(
            thread_id=thread.id,    # Usar el ID del thread para identificarlo
            run_id=run.id,          # Usar el ID del run para identificarlo
        )
        # Espera 0.1 segundos antes de la próxima consulta
        t.sleep(0.4)
        
    # Devuelve el objeto run actualizado, que ahora debería tener un estado final
    return run

class EventHandler(AssistantEventHandler):
    '''
    Maneja los eventos generados por un asistente y
    proporciona respuestas adecuadas a las acciones requeridas.

    Métodos:
        on_text_created(text):
            Maneja el evento cuando se crea un nuevo texto por parte del asistente.

        on_text_delta(delta, snapshot):
            Procesa las deltas de texto generadas por el asistente.

        on_tool_call_created(tool_call):
            Maneja la creación de una llamada a una herramienta por parte del asistente.

        on_tool_call_delta(delta, snapshot):
            Procesa las deltas de las llamadas a herramientas,
            específicamente para el tipo 'code_interpreter'.

        handle_requires_action(data, run_id):
            Gestiona las acciones requeridas, como enviar salidas de herramientas
            en función de las solicitudes del asistente.
    '''
    @override
    def on_text_created(self, text) -> None:
        print("\nassistant > ", end="", flush=True)

    @override
    def on_text_delta(self, delta, snapshot):
        print(delta.value, end="", flush=True)

    @override
    def on_tool_call_created(self, tool_call):
        print(f"\nassistant > {tool_call.type}\n", flush=True)

    @override
    def on_tool_call_delta(self, delta, snapshot):
        if delta.type == 'code_interpreter':
            if delta.code_interpreter.input:
                print(delta.code_interpreter.input, end="", flush=True)
            if delta.code_interpreter.outputs:
                print("\n\noutput >", flush=True)
                for output in delta.code_interpreter.outputs:
                    if output.type == "logs":
                        print(f"\n{output.logs}", flush=True)

    @override
    def handle_requires_action(self, data, run_id):
        tool_outputs = []
        for tool in data.required_action.submit_tool_outputs.tool_calls:
            if tool.function.name == "get_current_temperature":
                tool_outputs.append({"tool_call_id": tool.id, "output": "57"})
            elif tool.function.name == "get_rain_probability":
                tool_outputs.append({"tool_call_id": tool.id, "output": "0.06"})

        # Submit all tool_outputs at the same time
        self.submit_tool_outputs(tool_outputs, run_id)

# Diccionario para almacenar datos de usuarios, como ID de hilos y mensajes
user_data = {}

# Funciones setter para gestionar el estado del hilo y mensajes de los usuarios
def set_thread_id(telegram_id: int, thread_id: int) -> None:
    '''
    Establece el ID de hilo para un usuario específico (telegram_id)
    en el diccionario `user_data`.
    No retorna ningún valor.
    '''
    user_data.setdefault(telegram_id, {})['thread_id'] = thread_id

def set_first_msg_id(telegram_id: int, first_msg_id: int) -> None:
    '''
    Establece el ID del primer mensaje para un usuario específico (telegram_id)
    en el diccionario `user_data`.
    No retorna ningún valor.
    '''
    user_data.setdefault(telegram_id, {})['first_msg_id'] = first_msg_id

# Funciones getter para obtener el estado del hilo y mensajes de los usuarios
def get_thread_id(telegram_id: int) -> int|None:
    '''
    Esta función busca el ID del hilo (`thread_id`) asociado con
    un usuario específico (telegram_id) en el diccionario global `user_data`.
    Si no existe una entrada para el `telegram_id` proporcionado,
    o si no se ha asignado un ID de hilo, la función retornará `None`.
    '''
    return user_data.get(telegram_id, {}).get('thread_id')

def get_first_msg_id(telegram_id: int) -> int|None:
    '''
    Esta función busca el ID del primer mensaje (`first_msg_id`) asociado con
    un usuario específico (telegram_id) en el diccionario global `user_data`.
    Si no existe una entrada para el `telegram_id` proporcionado,
    o si no se ha asignado un ID de primer mensaje, la función retornará `None`.
    '''
    return user_data.get(telegram_id, {}).get('first_msg_id')

def handle_message(update: Update, context: CallbackContext):
    '''
    Maneja un mensaje entrante de Telegram, crea un hilo de conversación si no existe,
    envía el mensaje al asistente, gestiona las acciones requeridas y responde al
    usuario con el resultado.

    Args:
        update (Update): Actualización de Telegram que contiene información del mensaje entrante.
        context (CallbackContext): Contexto proporcionado por el manejador de comandos de Telegram.
    '''
    telegram_id = update.message.chat_id
    text = update.message.text

    # Enviar acción de "escribiendo..."
    context.bot.send_chat_action(chat_id=telegram_id, action=ChatAction.TYPING)

    # Obtener el ID del hilo (thread) una vez y reutilizarlo
    thread_id = get_thread_id(telegram_id)

    if not get_thread_id(telegram_id):
        thread = client.beta.threads.create()
        thread_id = thread.id
        set_thread_id(telegram_id, thread_id)
        set_first_msg_id(telegram_id, None)
    else:
        thread = client.beta.threads.retrieve(thread_id)
        print(f"Retrieved thread: {thread_id}")

    # Enviar el mensaje al asistente
    try:
        message = client.beta.threads.messages.create(
            thread_id = thread_id,
            role = "user",
            content = text
        )
        print(f"Created message: {message}")
    except (RequestException, ConnectionError, ValueError,
            KeyError, TypeError, PermissionError) as e:
        print(f"Error occurred while creating message: {e}")
        return

    # Crear y gestionar la corrida (run)
    try:
        run = client.beta.threads.runs.create_and_poll(
            thread_id = thread_id,
            assistant_id = assistant.id
        )
        print(f"Run created and polled. Run status: {run.status}")
    except (RequestException, ValueError, KeyError) as e:
        print(f"Error occurred during run creation or polling: {e}")
        return

    # Gestionar la acción requerida si el estado del run es 'requires_action'
    if run.status == 'requires_action':
        print (">>> Entrando a requires_action")
        tool_call = run.required_action.submit_tool_outputs.tool_calls[0]
        name = tool_call.function.name
        arguments = json.loads(tool_call.function.arguments)

        # Usar un diccionario para mapear nombres de funciones a referencias
        function_map = {
            "iniciar_agendar_cita": iniciar_agendar_cita,
            "completar_agendar_cita": completar_agendar_cita,
            "consultar_disponibilidad": consultar_disponibilidad,
            "buscar_cita_a_cancelar": buscar_cita_a_cancelar,
            "confirmar_cita_a_cancelar": confirmar_cita_a_cancelar,
            "consultar_citas_agendadas": consultar_citas_agendadas,
            "iniciar_modificar_cita": iniciar_modificar_cita,
            "confirmar_modificar_cita": confirmar_modificar_cita
        }

        # Obtener la función a ejecutar de forma segura
        respuesta_funcion = function_map.get(name)
        if not respuesta_funcion:
            print(f"No function named {name} found.")
            return

        print(f"Llamando a función {name}")
        print ("Argumentos recibidos:\n", arguments)

        # Ejecutar la función y obtener el resultado
        result = respuesta_funcion(arguments)

        # Asegurarse de que el resultado es una cadena
        if isinstance(result, dict):
            result = json.dumps(result)
        elif not isinstance(result, str):
            result = str(result)

        # Convertir el resultado a cadena de texto si no lo es
        if isinstance(result, dict):
            result = json.dumps(result)  # Convertir diccionario a cadena JSON
        elif not isinstance(result, str):
            result = str(result)

        print("Resultado tras ejecutar la función:")
        print(result)
        print()

        # Enviar el resultado de la llamada a la función
        try:
            run = client.beta.threads.runs.submit_tool_outputs(
                thread_id = thread_id,
                run_id = run.id,
                tool_outputs = [
                    {"tool_call_id": tool_call.id, "output": result}
                ],
            )
            print(f"Tool outputs submitted successfully. Run status: {run.status}")
        except (RequestException, ValueError, KeyError, TypeError, TimeoutError) as e:
            print(f"Error occurred while submitting tool outputs: {e}")
            return

        # Mostrar información de depuración
        # show_json(run)

        # Esperar a que el run se complete
        run = wait_on_run(run, thread)

    # Listar los mensajes en el hilo
    first_msg_id = get_first_msg_id(telegram_id)
    try:
        messages = client.beta.threads.messages.list(thread_id, before=first_msg_id)
        print("Messages listed successfully.")
    except (RequestException, ConnectionError, ValueError,
            KeyError, TypeError, PermissionError) as e:
        print(f"Error occurred while listing messages: {e}")
        return

    # Actualizar el ID del primer mensaje
    set_first_msg_id(telegram_id, messages.first_id)

    for m in messages.data:
        if m.role == 'assistant' and m.content and m.content[0].text:
            context.bot.send_message(chat_id = telegram_id, text = m.content[0].text.value)

def handle_location(update: Update, context: CallbackContext):
    '''
    Maneja la recepción de una ubicación enviada por el usuario.

    Esta función se activa cuando el bot recibe un mensaje que contiene una ubicación.
    Envía un mensaje al chat del usuario confirmando la recepción de la ubicación.

    Args:
        update (Update): Un objeto que contiene información sobre el mensaje recibido,
            incluyendo los datos del chat y del mensaje.
        context (CallbackContext): Un objeto que contiene información adicional del contexto
            en el que se está ejecutando el manejador, como el bot.

    Returns:
        None
    '''
    chat_id = update.message.chat_id
    context.bot.send_message(
        chat_id = chat_id,
        text = "Recibí tu ubicación."
    )

def handle_photo(update: Update, context: CallbackContext):
    '''
    Maneja la recepción de una foto enviada por el usuario.

    Esta función se activa cuando el bot recibe un mensaje que contiene una foto
    La foto es procesada para obtener su URL, y se envía un mensaje de texto al chat
    del usuario con una solicitud para proporcionar información sobre el medicamento.
    Luego, se envía la foto junto con el mensaje al cliente de la API para
    obtener una respuesta sobre el contenido de la imagen.

    Args:
        update (Update): Un objeto que contiene información sobre el mensaje recibido,
            incluyendo los datos del chat y del mensaje.
        context (CallbackContext): Un objeto que contiene información adicional del contexto
            en el que se está ejecutando el manejador, como el bot.

    Returns:
        None

    Raises:
        Exception: Si ocurre un error al procesar la imagen o al comunicarse con la API,
        se imprime el error y se envía un mensaje de error al chat del usuario.
    '''
    chat_id = update.message.chat_id
    photo_file = update.message.photo[-1].get_file()
    photo_url = photo_file.file_path

    if update.message.caption:
        user_message = update.message.caption
    else:
        user_message = "¿Para qué sirve este medicamento?"

    # Mensaje adicional
    additional_message = (
        """Proporciona de forma resumida el propósito y las instrucciones de uso, 
        haciendo hincapié en la obligatoriedad de la prescripción médica para aquellos 
        medicamentos que así estén prescritos. En caso de que se solicite información 
        sobre un medicamento que requiera prescripción médica, proporciona información 
        sobre el doctor del Hospital Clínico más apropiado para consultarle, y pregunta 
        si deseo agendar una cita médica con el mismo. Importante: si el medicamento no 
        es conocido, indica de forma amable que no lo conoces y sugiere consultar con 
        un profesional."""
    )
    user_message += " " + additional_message

    print(f"URL de la imagen: {photo_url}")

    context.bot.send_chat_action(chat_id = chat_id, action = ChatAction.TYPING)

    response = client.chat.completions.create(
        model = "gpt-4o",
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_message},
                    {"type": "image_url", "image_url": {"url": photo_url}},
                ],
            }
        ],
        max_tokens = 300,
    )

    try:
        content = response.choices[0].message.content
        print(f"Contenido de la imagen: {content}")
        context.bot.send_message(
            chat_id = chat_id,
            text = content
        )
    except Exception as e:
        print(f"Error al procesar la imagen: {e}")
        context.bot.send_message(
            chat_id = chat_id,
            text = "No se pudo obtener el contenido de la imagen."
        )

def main():
    '''
    Programa principal "main"
    '''
    try:
        updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
        dispatcher = updater.dispatcher

        dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
        dispatcher.add_handler(MessageHandler(Filters.location, handle_location))
        dispatcher.add_handler(MessageHandler(Filters.photo, handle_photo))

        updater.start_polling()
        updater.idle()
    except Exception as e:
        logging.error("Error ocurrido: %s", str(e))
        raise

if __name__ == '__main__':
    main()