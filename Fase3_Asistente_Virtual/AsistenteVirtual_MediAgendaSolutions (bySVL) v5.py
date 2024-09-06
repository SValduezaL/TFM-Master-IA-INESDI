'''
Asistente Virtual Basilio para MediAgendaSolutions
'''

# Importar datetime para manejar fechas y horas
import time as t
from datetime import datetime, time, timedelta
from typing import Dict, List, Union

import json
import os
import logging

# Importar la biblioteca OpenAI
from openai import OpenAI, AssistantEventHandler

# Importar override de typing_extensions
from typing_extensions import override

# Importar gspread para Google Sheets
import gspread
from google.oauth2.service_account import Credentials

# Importar módulos de Telegram (python-telegram-bot==13.14)
from telegram import Update, ChatAction  # Unused Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, MessageHandler, Filters, CallbackContext
)   # CommandHandler, CallbackQueryHandler

# Importar requests para realizar solicitudes HTTP
from requests.exceptions import RequestException

# Inicializar el cliente de OpenAI con la clave API proporcionada
client = OpenAI(api_key='sk-proj-Uced5j5iSx13bk7IUtbLT3BlbkFJmJpHhTPQDRZaLtuivsUc')
ASSISTANT_ID = 'asst_EIzfKfeuWhBEj2nJR2O3iucy' # MediAgenda Solutions (SVL)
assistant = client.beta.assistants.retrieve(assistant_id = ASSISTANT_ID)

# Inicializar el cliente de Telegram con el token del bot
TELEGRAM_TOKEN = '7193381473:AAHNVUdTBPXKCB0rMXGeOwsY53r90nG6eyg' # Basilio_MediAgenda_bot

# Función para mostrar JSON en consola, usada para depuración
def show_json(obj):
    '''
    Muestra un objeto json en consola
    '''
    print(json.loads(obj.model_dump_json()))

# Configuración de credenciales de Google Sheets para acceder a las hojas de cálculo
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
# Obtener el directorio del script
script_dir = os.path.dirname(os.path.abspath(__file__))
# Construir la ruta al archivo JSON basado en el directorio del script
json_path = os.path.join(script_dir, 'mediagenda-solutions-5e8208b2d6a6.json')
# Credenciales
creds = Credentials.from_service_account_file(json_path, scopes = scope)
client_gspread = gspread.authorize(creds)

# ID de la hoja de cálculo de Google Sheets
SPREADSHEET_ID = '1IuMVqClEJ-qhJxnXb02TunbI1rxMvmj4IO863Nf5ygg' # agenda_medica_HC (SVL)

# Abrir la hoja de cálculo por su ID y seleccionar las hojas necesarias
spreadsheet = client_gspread.open_by_key(SPREADSHEET_ID)
agenda_worksheet = spreadsheet.sheet1  # Hoja para agendar citas
medico_worksheet = spreadsheet.get_worksheet(1)  # Hoja con médicos y especialidades

def buscar_medicos_especialidades(
    identificador: str,
    por: str = "especialidad"
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

    if por == "especialidad":
        # Buscar la fila donde la primera columna coincide con la especialidad
        medicos = list({row[1] for row in all_rows if row[0] == identificador})
        return medicos

    if por == "medico":
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
    medicos_con_citas_reservadas = set(
        cita[0] for cita in citas_reservadas
        if cita[1] == fecha and cita[2] == hora
    )
    medicos_libres = list(set(medicos) - medicos_con_citas_reservadas)
    hay_medicos_libres = bool(medicos_libres)
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
        fecha (str): Fecha de la cita en formato YYYY-MM-DD.
        identificador (str): Dependiendo del tipo de consulta, especifica la
            especialidad médica o el nombre del médico.
        hora (str, opcional): Hora de la cita en formato HH:MM.
            Por defecto = ""
        tipo_verificacion (str, opcional): Tipo de identificación ("especialidad" o "medico").
            Por defecto = "especialidad"

    Returns:
        Dict: Un dicionario con las siguientes claves:
            "existe_disponibilidad" (bool):
                True: Existe disponibilidad para la fecha (y hora) indicadas.
                False: No existe disponibilidad para la fecha (y hora) indicadas.
            "medicos_libres" (List[str]): Conjunto de médicos con disponibilidad
                a las horas indicadas.
            "horas_disponibles" (List[str]): Listado con las horas disponibles.
            "mensaje" (str): Mensaje de error o informativo.
    '''
    hora_inicio_dt = time(8, 0)  # 8:00 AM
    hora_fin_dt = time(19, 0)   # 7:00 PM
    duracion_cita = timedelta(minutes=20)

    if tipo_verificacion == "especialidad":
        # Buscar los médicos de dicha especialidad si el tipo es "especialidad"
        medicos = buscar_medicos_especialidades(identificador, por = "especialidad")
        if not medicos:
            return {
                "existe_disponibilidad": False,
                "medicos_libres": [],
                "horas_disponibles": [],
                "mensaje": f"No disponemos de médicos para dicha especialidad ({identificador})."
            }

    else:
        # Verificar si el médico existe
        medicos = []
        all_rows = medico_worksheet.get_all_values()
        for row in all_rows:
            if row[1] == identificador:
                medicos.append(identificador)
                break
        if not medicos:
            return {
                "existe_disponibilidad": False,
                "medicos_libres": [],
                "horas_disponibles": [],
                "mensaje": f"No disponemos del médico {identificador} en nuestra Clínica."
            }

    # Filtrar las citas del médico (o médicos) y fecha especificadas
    citas_reservadas = [
        (row[1], row[5], row[6])
        for row in agenda_worksheet.get_all_values()
        if row[1] in medicos and row[5] == fecha and row[7].lower() != 'cancelada'
    ]

    # SI NO SE ESPECIFICA UNA HORA:
    # Devolver True con todas las horas disponibles (o False si no las hay)
    if not hora:
        horas_disponibles = []
        medicos_libres = set()
        hora_actual_dt = datetime.combine(datetime.strptime(fecha, '%Y-%m-%d'), hora_inicio_dt)

        while hora_actual_dt.time() < hora_fin_dt:
            hora_actual_str = hora_actual_dt.strftime('%H:%M')
            for medico in medicos:
                if (medico, fecha, hora_actual_str) not in citas_reservadas:
                    medicos_libres.add(medico)
                    if hora_actual_str not in horas_disponibles:
                        horas_disponibles.append(hora_actual_str)
            hora_actual_dt += duracion_cita

        if horas_disponibles:
            return {
                "existe_disponibilidad": True,
                "medicos_libres": list(medicos_libres),
                "horas_disponibles": horas_disponibles,
                "mensaje": f"Para la fecha {fecha} hay horarios disponibles: {horas_disponibles}."
            }
        return {
            "existe_disponibilidad": False,
            "medicos_libres": [],
            "horas_disponibles": [],
            "mensaje": f"Para la fecha {fecha} no hay horarios disponibles."
        }

    # SI SE ESPECIFICA UNA HORA:
    # Redondeamos la hora al múltiplo de 20min más cercano
    hora_redondeada = redondear_a_multiplo_20_minutos(hora)
    hora_actual_redondeada_dt = datetime.strptime(hora_redondeada, '%H:%M').time()

    # Verificar si la hora solicitada es una hora válida dentro del horario de atención
    if not hora_inicio_dt <= hora_actual_redondeada_dt < hora_fin_dt:
        return {
            "existe_disponibilidad": False,
            "medicos_libres": [],
            "horas_disponibles": [],
            "mensaje": "Hora no válida. Por favor elige una hora dentro del horario de atención."
        }

    hay_medicos_libres, medicos_libres = comprobar_si_hay_medicos_libres(
        medicos = medicos,
        citas_reservadas = citas_reservadas,
        fecha = fecha,
        hora = hora_redondeada
    )

    # Devolver True si hay algún médico libre
    if hay_medicos_libres:
        return {
            "existe_disponibilidad": True,
            "medicos_libres": list(medicos_libres),
            "horas_disponibles": [hora_redondeada],
            "mensaje": f"Hay hora disponible a las {hora_redondeada} con {medicos_libres}."
        }

    # Si no hay médicos libres, buscar la siguiente hora disponible para cualquiera de ellos
    fecha_actual_dt = datetime.strptime(fecha, '%Y-%m-%d')
    hora_actual_dt = datetime.combine(fecha_actual_dt, hora_actual_redondeada_dt) + duracion_cita
    while hora_actual_dt.time() < hora_fin_dt:
        hora_actual_str = hora_actual_dt.strftime('%H:%M')
        hay_medicos_libres, medicos_libres = comprobar_si_hay_medicos_libres(
            medicos = medicos,
            citas_reservadas = citas_reservadas,
            fecha = fecha,
            hora = hora_actual_str
        )

        # Devolver False indicando la siguiente hora disponible en el mismo día
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

        hora_actual_dt += duracion_cita

    # Devolver False indicando que no hay horas disponibles después de la hora solitada
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
    # Generar un nuevo ID incrementando el mayor ID existente
    ids = [int(row[0]) for row in all_rows if row[0].isdigit()]
    if ids:
        return max(ids) + 1
    return 1

# Un diccionario para almacenar el estado de las conversaciones
#   para agendar citas
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
            "tipo_agendamiento" (str): Tipo de identificación ("especialidad" o "medico").
            "identificador" (str): Dependiendo del tipo de consulta, especifica la
                especialidad médica o el nombre del médico.
            "name" (str): Nombre del paciente.
            "dni" (str): Identificación del paciente.
            "fecha" (str): Fecha de la cita en formato YYYY-MM-DD.
            "hora" (str): Hora de la cita en formato HH:MM.

    Returns:
        str: Mensaje de solicitud para completar el agendamiento, o de error.
    '''
    print(f"Entrando en la función iniciar_agendar_cita con params: {params}")

    tipo = params.get('tipo_agendamiento')
    identificador = params.get('identificador')  # Puede ser especialidad o nombre del médico
    name = params.get('name')
    dni = params.get('dni')
    fecha = params.get('fecha')
    hora = redondear_a_multiplo_20_minutos(params.get('hora'))

    # Inicializamos los posibles conjuntos de médicos y especialidades disponibles
    medicos = set()
    especialidades = set()

    if tipo == "especialidad":
        especialidad = identificador
        # Buscar el nombre del médico si no se proporciona
        medicos = buscar_medicos_especialidades(especialidad, por = "especialidad")
        if not medicos:
            return f"No se encontró a ningún médico para la especialidad {especialidad}."
        print(f"Nombre del/los médico/s para la especialidad {especialidad}: {medicos}")

        # Verificar la disponibilidad de la cita por especialidad
        print(f"Verificando disponibilidad por especialidad: {especialidad}")
        disponibilidad = verificar_disponibilidad(
            fecha = fecha,
            identificador = especialidad,
            hora = hora,
            tipo_verificacion = "especialidad"
        )

        if not disponibilidad['existe_disponibilidad']:
            print(f"Error en disponibilidad: {disponibilidad['mensaje']}")
            return disponibilidad['mensaje']

        # Si hay más de un médico se solicita al usuario que lo elija
        if len(disponibilidad['medicos_libres']) > 1:
            # Incializamos y guardamos el estado de conversación
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

            mensaje = f"Hay varios médicos disponibles para la especialidad {especialidad}. \
¿Cuál prefieres?\n{' / '.join(disponibilidad['medicos_libres'])}"
            return mensaje

        medico = disponibilidad['medicos_libres'][0]

    elif tipo == "medico":
        medico = identificador
        # Buscar la especialidad del médico si no se proporciona
        especialidades = buscar_medicos_especialidades(medico, por = "medico")
        if not especialidades:
            return f"No se encontró una especialidad para el médico {medico}."
        print(f"Nombre de la/s especialidad/es para el médico {medico}: {especialidades}")

        # Verificar la disponibilidad de la cita por médico
        print(f"Verificando disponibilidad por médico: {medico}")
        disponibilidad = verificar_disponibilidad(
            fecha = fecha,
            identificador = medico,
            hora = hora,
            tipo_verificacion = "medico"
        )

        if not disponibilidad['existe_disponibilidad']:
            print(f"Error en disponibilidad: {disponibilidad['mensaje']}")
            return disponibilidad['mensaje']

        # Si hay más de una especialidad se solicita al usuario que la elija
        if len(especialidades) > 1:
            # Incializamos y guardamos el estado de conversación
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

            mensaje = f"Hay varias especialidad disponibles para el/la {medico}. \
¿Cuál prefieres?\n{' / '.join(especialidades)}"
            return mensaje

        especialidad = especialidades[0]

    # Obtener un nuevo ID para la cita
    cita_id = obtener_nuevo_id_cita()
    print(f"Nuevo ID de cita: {cita_id}")

    # Agregar la cita a la hoja agenda_worksheet
    first_empty_row = len(agenda_worksheet.get_all_values()) + 1

    cita_data = [
        [cita_id, medico, especialidad, name,
        dni, fecha, hora, 'Programada',
        datetime.now().strftime('%Y-%m-%d %H:%M:%S')]
    ]
    print(f"Cita a agendar: {cita_data}")

    # Actualiza los datos en bloque
    agenda_worksheet.update(
        f'A{first_empty_row}:I{first_empty_row}',
        cita_data,
        value_input_option='USER_ENTERED'
    )

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
    # Obtener todas las filas de la hoja medico_worksheet
    all_rows = medico_worksheet.get_all_values()

    # Recuperamos estado de la agendizamiento de cita
    estado = obtener_estado_conversacion(params.get('dni'))
    dni = estado.get('dni')
    name = estado.get('name')
    medico = estado.get('medico')
    especialidad = estado.get('especialidad')
    fecha = estado.get('fecha')
    hora = estado.get('hora')

    if not medico:
        medico = params.get('seleccion')
        medicos = {row[1] for row in all_rows}
        if medico not in medicos:
            return "Error: Selección no válida. Vuelve a indicar el médico deseado."

    if not especialidad:
        especialidad = params.get('seleccion')
        especialidades = {row[0] for row in all_rows}
        if especialidad not in especialidades:
            return "Error: Selección no válida. Vuelve a indicar la especialidad deseada."

    # Obtener un nuevo ID para la cita
    cita_id = obtener_nuevo_id_cita()
    print(f"Nuevo ID de cita: {cita_id}")

    # Agregar la cita a la hoja agenda_worksheet
    first_empty_row = len(agenda_worksheet.get_all_values()) + 1

    cita_data = [
        [cita_id, medico, especialidad, name,
        dni, fecha, hora, 'Programada',
        datetime.now().strftime('%Y-%m-%d %H:%M:%S')]
    ]
    print(f"Cita a agendar: {cita_data}")

    # Actualiza los datos en bloque
    agenda_worksheet.update(
        f'A{first_empty_row}:I{first_empty_row}',
        cita_data,
        value_input_option='USER_ENTERED'
    )

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
    identificador = params.get('identificador')  # Puede ser especialidad o nombre del médico
    fecha_inicio = params.get('fecha_inicio')
    fecha_fin = params.get('fecha_fin')

    if not tipo_consulta or not identificador or not fecha_inicio:
        return {
            "exito_consulta": False,
            "disponibilidades": {},
            "mensaje": "Faltan parámetros obligatorios: \
'tipo_consulta', 'identificador' o 'fecha_inicio'."
        }

    # # Validación y conversión de fechas
    try:
        fecha_inicio_dt = datetime.strptime(fecha_inicio, '%Y-%m-%d')
        # Si fecha_fin no se proporciona, la fecha_fin es igual a la fecha_inicio
        if fecha_fin:
            fecha_fin_dt = datetime.strptime(fecha_fin, '%Y-%m-%d')
        else:
            fecha_fin_dt = fecha_inicio_dt
    except ValueError as e:
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

    # Inicialización de disponibilidad
    disponibilidades = {}
    fecha_actual_dt = fecha_inicio_dt

    # Consulta de disponibilidad por fecha
    while fecha_actual_dt <= fecha_fin_dt:
        fecha_actual_str = fecha_actual_dt.strftime('%Y-%m-%d')

        # Llamada a la función que verifica la disponibilidad para una fecha específica
        disponibilidad = verificar_disponibilidad(
            fecha = fecha_actual_str,
            identificador = identificador,
            hora = None,
            tipo_verificacion = tipo_consulta
        )

        if disponibilidad['existe_disponibilidad']:
            disponibilidades[fecha_actual_str] = {
                "horas_disponibles": disponibilidad['horas_disponibles'],
                "medicos_libres": disponibilidad['medicos_libres']
            }
        else:
            print(disponibilidad['mensaje'])

        fecha_actual_dt += timedelta(days=1)

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

#def enviar_disponibilidad_con_botones(
#    update: Update,
#    context: CallbackContext,
#    disponibilidad: Dict[str, List[str]]
#) -> None:
#    '''
#    Envía un mensaje al usuario con un teclado inline que permite seleccionar
#    una fecha y hora disponible.
#
#    Args:
#        update (Update): Objeto de Telegram que contiene la información
#            de la actualización recibida.
#        context (CallbackContext): Contexto del callback,
#            que contiene información adicional como el bot.
#        disponibilidad (Dict[str, List[str]]): Disponibilidad en formato
#            de diccionario o cadena JSON.
#            El diccionario debe tener fechas como claves y listas de horas como valores.
#
#    Returns:
#        None
#    '''
#    # Verificar si el argumento es una cadena JSON y convertirlo a un diccionario
#    if isinstance(disponibilidad, str):
#        try:
#            disponibilidad = json.loads(disponibilidad)
#        except json.JSONDecodeError:
#            context.bot.send_message(
#                chat_id = update.message.chat_id,
#                text = "Error al procesar la disponibilidad."
#            )
#            return
#
#    # Inicializar el teclado
#    keyboard = []
#
#    # Recorrer las fechas y horas disponibles para crear los botones
#    for fecha, horas in disponibilidad.items():
#        # Crear un botón para la fecha
#        row = []
#        fecha_button = InlineKeyboardButton(fecha, callback_data = None)
#        row.append(fecha_button)
#        keyboard.append(row)
#
#        # Crear botones para cada hora asociada a la fecha, en otra fila
#        row = []
#        for hora in horas:
#            hora_button = InlineKeyboardButton(hora, callback_data = f"{fecha}:{hora}")
#            row.append(hora_button)
#            if len(row) == 3:
#                keyboard.append(row)
#                row = []
#        # Añadir la última fila de horas si no está vacía
#        if row:
#            keyboard.append(row)
#
#    reply_markup = InlineKeyboardMarkup(keyboard)
#    context.bot.send_message(
#        chat_id = update.message.chat_id,
#        text = "Selecciona una fecha y hora:",
#        reply_markup = reply_markup
#    )

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
    all_rows = agenda_worksheet.get_all_values()

    for row in all_rows:
        if row[4] == dni:
            return True, row[3]

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

def cancelar_cita(params: dict) -> Dict[str, Union[bool, str]]:
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
    print(f"Entrando en la función cancelar_cita con params: {params}")

    cita_id = params.get('cita_id')
    dni = params.get('dni')
    fecha = params.get('fecha')
    hora = params.get('hora')

    if not dni:
        return {
            'cita_cancelada': False,
            'mensaje_cancelacion': "DNI no proporcionado."
        }

    # Buscar el nombre del paciente usando el DNI
    paciente_encontrado, nombre_paciente = buscar_paciente(dni)
    if not paciente_encontrado:
        return {
            'cita_cancelada': False,
            'mensaje_cancelacion': f"No se encontró a ningún paciente con el DNI {dni}."
        }

    # Obtener todas las citas no canceladas de la hoja agenda_worksheet
    all_rows = agenda_worksheet.get_all_values()
    rows_not_cancelled = [row for row in all_rows if row[7].lower() != 'cancelada']

    cita = None

    # Buscar y cancelar la cita por ID
    if cita_id:
        for row in rows_not_cancelled:
            if row[0] == str(cita_id) and row[4] == dni:
                cita = row
                break
        resultado_no_hay_cita = {
            'cita_cancelada': False,
            'mensaje_cancelacion': f"No se encontró la cita {cita_id} \
a nombre de {nombre_paciente} (DNI {dni})."
        }
    else:
        if not (fecha and hora):
            return {
                'cita_cancelada': False,
                'mensaje_cancelacion': "Si no se proporciona 'cita_id' \
se debe proporcionar 'fecha' y 'hora', o viceversa."
            }
        for row in rows_not_cancelled:
            if row[4] == dni and row[5] == fecha and row[6] == hora:
                cita = row
                break
        resultado_no_hay_cita = {
            'cita_cancelada': False,
            'mensaje_cancelacion': f"No se encontró la cita de {nombre_paciente} (DNI {dni}) \
para el {fecha} a las {hora}."
        }

    if cita:
        actualizar_estado_cancelacion(dni, {'row': cita})
        return {
            'cita_cancelada': False,
            'mensaje_cancelacion': f"¿Seguro que deseas cancelar la Cita de \
{cita[3]} (DNI {cita[4]}) con ID {cita[0]}, programada para el {cita[5]} a las {cita[6]} \
con el médico {cita[1]} (Especialidad: {cita[2]}?"
        }

    return resultado_no_hay_cita

def confirmacion_cancelacion(params: dict) -> Dict[str, Union[bool, str]]:
    """
    Confirma la cancelación de una cita según la elección del usuario.

    Args:
        params (dict): Un diccionario con la siguiente clave:
            "dni" (str): Identificador del usuario (DNI). 
            "eleccion" (str): Confirmación del Usuario ("SI" o "NO").

    Returns:
        Returns:
            Dict: Un diccionario con las siguientes claves:
                "cita_cancelada" (bool): Indica si la cita fue cancelada o no..
                "mensaje_cancelacion" (str): Mensaje informativo.
    """
    print(f"Entrando en la función confirmar_cancelacion con params: {params}")

    dni = params.get('dni')
    eleccion = params.get('eleccion')

    if not dni or not eleccion:
        return {
            'cita_cancelada': False,
            'mensaje_cancelacion': "DNI y elección de confirmación son requeridos."
        }

    # Recuperamos la cita de la que se quiere confirmar cancelación
    cita = obtener_estado_cancelacion(dni)
    if not cita:
        return {
            'cita_cancelada': False,
            'mensaje_cancelacion': f"No hay una cita pendiente de confirmación para el DNI {dni}."
        }

    row = cita.get('row')
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

    if eleccion.upper() == 'SI':
        # Obtener todas las citas de la hoja agenda_worksheet
        all_rows = agenda_worksheet.get_all_values()
        # Encontrar la fila original en la hoja de cálculo completa
        original_row = all_rows.index(row) + 1
        # Cancelar cita
        agenda_worksheet.update_cell(original_row, 8, 'Cancelada')
        return {
            'cita_cancelada': True,
            'mensaje_cancelación': f"Cita de {nombre_paciente} (DNI {dni}) \
con ID {cita_id}, programada para el {fecha} a las {row[6]} con el médico {medico} \
(Especialidad: {especialidad}) CANCELADA con éxito."
        }

    # Si no se confirma la cancelación
    return {
        'cita_cancelada': False,
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

    dni = params.get('dni')
    fecha_inicio = params.get('fecha_inicio')
    fecha_fin = params.get('fecha_fin')

    if not dni:
        return "El DNI del paciente es obligatorio."

    try:
        fecha_inicio_dt = datetime.strptime(fecha_inicio, '%Y-%m-%d') if fecha_inicio else None
        fecha_fin_dt = datetime.strptime(fecha_fin, '%Y-%m-%d') if fecha_fin else None
    except ValueError as e:
        return f"Formato de fecha inválido: {e}"

    # Si fecha_fin no se proporciona, se usa fecha_inicio como fecha_fin
    if fecha_inicio_dt and not fecha_fin_dt:
        fecha_fin_dt = fecha_inicio_dt

    if fecha_inicio_dt and fecha_fin_dt and fecha_inicio_dt > fecha_fin_dt:
        return "La fecha de inicio no puede ser posterior a la fecha de fin."

    # Obtener todas las filas de la hoja agenda_worksheet
    # all_rows = agenda_worksheet.get_all_values()
    all_rows = agenda_worksheet.get_all_values()
    rows_not_cancelled = [row for row in all_rows if row[7].lower() != 'cancelada']

    citas = []
    for row in rows_not_cancelled:
        if row[4] == dni:
            fecha_cita = datetime.strptime(row[5], '%Y-%m-%d')
            if ((fecha_inicio_dt is None or fecha_cita >= fecha_inicio_dt) and
                (fecha_fin_dt is None or fecha_cita <= fecha_fin_dt)):
                citas.append({
                    'cita_id': row[0],
                    'medico': row[1],
                    'especialidad': row[2],
                    'fecha': row[5],
                    'hora': row[6]
                })

    if citas:
        citas_str = "\n".join(formatear_cita(cita) for cita in citas)
        return f"Tus citas agendadas:\n{citas_str}"

    return "No se encontraron citas para el DNI proporcionado en el periodo especificado."



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
    while run.status in {"queued", "in_progress"}:
        run = client.beta.threads.runs.retrieve(
            thread_id=thread.id,
            run_id=run.id,
        )
        t.sleep(0.1)
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
            "cancelar_cita": cancelar_cita,
            "confirmacion_cancelacion": confirmacion_cancelacion,
            "consultar_citas_agendadas": consultar_citas_agendadas
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

#def handle_confirmation(update: Update, context: CallbackContext):
#    global pending_cancellation
#    telegram_id = update.message.chat_id
#    text = update.message.text.upper()
#
#    if pending_cancellation is not None:
#        if text == 'SI':  # Si el usuario confirma la cancelación
#            result = confirmar_cita_a_cancelar(pending_cancellation, 'SI')
#            context.bot.send_message(
#                chat_id = telegram_id,
#                text = result
#            )
#        else:
#            context.bot.send_message(
#                chat_id = telegram_id,
#                text = "Cancelación de cita no confirmada."
#            )
#
#        # Limpiar la acción pendiente después de manejar la confirmación
#        pending_cancellation = None
#    else:
#        context.bot.send_message(
#            chat_id = telegram_id,
#            text = "No hay ninguna acción pendiente que confirmar."
#        )

#def enviar_confirmacion_cancelacion(update: Update, context: CallbackContext, params):
#    '''
#    Envía un mensaje al usuario pidiendo confirmación para cancelar una cita.
#
#    :param update: Update de Telegram.
#    :param context: Contexto de CallbackContext.
#    :param cita_detalles: Detalles de la cita a cancelar.
#    '''
#    keyboard = [
#        [InlineKeyboardButton("Sí, cancelar", callback_data=f"cancelar_cita_confirmado:{params}")],
#        [InlineKeyboardButton("No, mantener cita", callback_data="cancelar_cita_cancelado")]
#    ]
#    reply_markup = InlineKeyboardMarkup(keyboard)
#    context.bot.send_message(
#        chat_id = update.message.chat_id,
#        text = "¿Estás seguro de que deseas cancelar esta cita?",
#        reply_markup = reply_markup
#    )
#
#def handle_callback_query(update: Update, context: CallbackContext):
#     query = update.callback_query
#     data = query.data
#
#     if data.startswith("cancelar_cita_confirmado:"):
#         params = json.loads(data.split(":")[1])
#         #result = cancelar_cita(params, confirmacion=True)
#         #context.bot.send_message(chat_id=query.message.chat_id, text=result)
#     elif data == "cancelar_cita_cancelado":
#         context.bot.send_message(
#             chat_id = query.message.chat_id,
#             text = "La cancelación ha sido cancelada."
#         )

#def button(update: Update, context: CallbackContext):
#     query = update.callback_query
#     data = json.loads(query.data)
#     confirm = data['confirm']
#     params = data['params']
#
#     #if confirm:
#         #mensaje = cancelar_cita(params, confirmacion=True)
#     #else:
#         #mensaje = "Cancelación de la cita abortada."
#
#     #query.edit_message_text(text=mensaje)

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
