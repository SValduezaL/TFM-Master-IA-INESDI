from openai import OpenAI, AssistantEventHandler
from typing_extensions import override
import json
import time
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, Bot, ChatAction, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import datetime 
import requests

# Inicializar el cliente de OpenAI con la clave API proporcionada
client = OpenAI(api_key='sk-proj-Uced5j5iSx13bk7IUtbLT3BlbkFJmJpHhTPQDRZaLtuivsUc')
assistant_id = 'asst_ewmd1rGhfmoDMWlinfQOQ5D0'
assistant = client.beta.assistants.retrieve(assistant_id=assistant_id)

# Inicializar el cliente de Telegram con el token del bot
TELEGRAM_TOKEN = '7365309172:AAHkGNnXzUPHyv8-Mo5VgiorIWTvIm_NXSo'

# Función para mostrar JSON en consola, usada para depuración
def show_json(obj):
    print(json.loads(obj.model_dump_json()))

# Configuración de credenciales de Google Sheets para acceder a las hojas de cálculo
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_file('C:\\Users\\nerea\\Downloads\\mediagenda-solutions-5e8208b2d6a6.json', scopes=scope)
client_gspread = gspread.authorize(creds)

# ID de la hoja de cálculo de Google Sheets
spreadsheet_id = '1QXAV39MG5pE9JD7YW4H3bJowMXoI72bjvcD4MBN7Jww'

# Abrir la hoja de cálculo por su ID y seleccionar las hojas necesarias
spreadsheet = client_gspread.open_by_key(spreadsheet_id)
agenda_worksheet = spreadsheet.sheet1  # Hoja para agendar citas
medico_worksheet = spreadsheet.get_worksheet(1)  # Hoja con médicos y especialidades

# Diccionario para almacenar datos de usuarios, como ID de hilos y mensajes
user_data = {}

# Funciones setter para gestionar el estado del hilo y mensajes de los usuarios
def set_thread_id(telegram_id, thread_id):
    user_data.setdefault(telegram_id, {})['thread_id'] = thread_id

def set_first_msg_id(telegram_id, first_msg_id):
    user_data.setdefault(telegram_id, {})['first_msg_id'] = first_msg_id

# Funciones getter para obtener el estado del hilo y mensajes de los usuarios
def get_thread_id(telegram_id):
    return user_data.get(telegram_id, {}).get('thread_id')

def get_first_msg_id(telegram_id):
    return user_data.get(telegram_id, {}).get('first_msg_id')

def buscar_medico_especialidad(identificador, tipo="especialidad"):
    """
    Busca el médico por especialidad o la especialidad por médico en la hoja de médicos.

    :param identificador: Especialidad o nombre del médico a buscar.
    :param tipo: Tipo de búsqueda ("especialidad" o "medico").
    :return: Nombre del médico si tipo es "especialidad" o especialidad si tipo es "medico", None si no se encuentra.
    """
    # Obtener todas las filas de la hoja medico_worksheet
    all_rows = medico_worksheet.get_all_values()
    
    if tipo == "especialidad":
         # Buscar la fila donde la primera columna coincide con la especialidad
        for row in all_rows:
            if row[0] == identificador:
                return row[1]  # Retornar el nombre del médico correspondiente
    elif tipo == "medico":
        # Buscar la fila donde la segunda columna coincide con el nombre del médico
        for row in all_rows:
            if row[1] == identificador:
                return row[0]  # Retornar la especialidad correspondiente
    return None  # Retornar None si no se encuentra la especialidad o médico

def verificar_disponibilidad(fecha, hora, identificador, tipo="especialidad"):
    """
    Verifica la disponibilidad para una cita médica en una fecha y hora específicas.
    
    :param fecha: Fecha de la cita en formato YYYY-MM-DD.
    :param hora: Hora de la cita en formato HH:MM (opcional).
    :param identificador: Especialidad o nombre del médico, según el tipo.
    :param tipo: Tipo de identificación ("especialidad" o "medico").
    :return: Una lista de horas disponibles si no se especifica hora, o un mensaje de error si la hora está ocupada.
    """
    hora_inicio = datetime.time(8, 0)  # 8:00 AM
    hora_fin = datetime.time(20, 0)   # 8:00 PM
    duracion_cita = datetime.timedelta(minutes=20)
    
    if tipo == "medico":
        # Buscar la especialidad del médico si el tipo es "medico"
        especialidad = buscar_medico_especialidad(identificador, tipo="medico")
        if not especialidad:
            return None, f"No se encontró la especialidad para el médico {identificador}."
    else:
        especialidad = identificador

    # Obtener todas las filas de la hoja agenda_worksheet
    all_rows = agenda_worksheet.get_all_values()
    
    # Filtrar las citas reservadas para la especialidad y fecha especificadas
    citas_reservadas = [(row[2], row[5], row[6]) for row in all_rows if row[2] == especialidad and row[5] == fecha]
    
    if hora:
        # Verificar si la hora solicitada es una hora válida dentro del horario de atención
        if not (hora_inicio <= datetime.datetime.strptime(hora, '%H:%M').time() <= hora_fin):
            return None, "Hora no válida. Por favor elige una hora dentro del horario de atención."
        
        # Verificar si la hora solicitada está en las citas reservadas
        for cita in citas_reservadas:
            if cita[2] == hora:
                # Si la hora solicitada está ocupada, buscar la siguiente hora disponible
                hora_actual = datetime.datetime.strptime(hora, '%H:%M') + duracion_cita
                while hora_actual.time() <= hora_fin:
                    hora_actual_str = hora_actual.strftime('%H:%M')
                    if (especialidad, fecha, hora_actual_str) not in citas_reservadas:
                        return None, f"La hora {hora} para la especialidad {especialidad} y fecha {fecha} ya está reservada. Prueba con la siguiente hora disponible: {hora_actual_str}."
                    hora_actual += duracion_cita
                return None, f"La hora {hora} y todas las horas siguientes para la especialidad {especialidad} y fecha {fecha} están reservadas."
        
        # Si la hora solicitada no está en las citas reservadas, agendar la cita
        return True, None
    
    # Si no se especifica hora, devolver todas las horas disponibles
    horas_disponibles = []
    hora_actual = datetime.datetime.combine(datetime.datetime.strptime(fecha, '%Y-%m-%d').date(), hora_inicio)
    while hora_actual.time() < hora_fin:
        hora_actual_str = hora_actual.strftime('%H:%M')
        if (especialidad, fecha, hora_actual_str) not in citas_reservadas:
            horas_disponibles.append(hora_actual_str)
        hora_actual += duracion_cita
    
    return horas_disponibles, None

def obtener_nuevo_id_cita():
    """
    Obtiene un nuevo ID de cita incrementando el mayor ID existente en la hoja de agenda_worksheet.

    :return: Un nuevo ID de cita.
    """
    # Obtener todas las filas de la hoja agenda_worksheet
    all_rows = agenda_worksheet.get_all_values()
    # Generar un nuevo ID incrementando el mayor ID existente
    ids = [int(row[0]) for row in all_rows if row[0].isdigit()]
    if ids:
        return max(ids) + 1
    else:
        return 1
    
def agendar_cita(params):
    """
    Agenda una cita médica ya sea por especialidad o por médico.

    :param params: Diccionario con parámetros necesarios para agendar la cita.
    :return: Mensaje de confirmación o error.
    """
    print(f"Entrando en la función agendar_cita con params: {params}")

    tipo = params.get('tipo')
    fecha = params.get('fecha')
    hora = params.get('hora')
    identificador = params.get('identificador')  # Puede ser especialidad o nombre del médico
    name = params.get('name')
    dni = params.get('dni')
    
    if tipo == "especialidad":
        # Verificar la disponibilidad de la cita por especialidad
        especialidad = identificador
        print(f"Verificando disponibilidad por especialidad: {especialidad}")
        disponibilidad, mensaje_error = verificar_disponibilidad(fecha, hora, especialidad, tipo="especialidad")
        if not disponibilidad:
            print(f"Error en disponibilidad: {mensaje_error}")
            return mensaje_error
        
        # Buscar el nombre del médico si no se proporciona
        medico = buscar_medico_especialidad(especialidad, tipo="especialidad")
        print(f"Nombre del médico para la especialidad {especialidad}: {medico}")
        
        if not medico:
            return f"No se encontró un médico para la especialidad {especialidad}."
    elif tipo == "medico":
        # Verificar la disponibilidad de la cita por médico
        medico = identificador
        especialidad = buscar_medico_especialidad(medico, tipo="medico")
        if not especialidad:
            return f"No se encontró una especialidad para el médico {medico}."
        print(f"Verificando disponibilidad por médico: {medico}")
        disponibilidad, mensaje_error = verificar_disponibilidad(fecha, hora, medico, tipo="medico")
        if not disponibilidad:
            print(f"Error en disponibilidad: {mensaje_error}")
            return mensaje_error

    # Obtener un nuevo ID para la cita
    cita_id = obtener_nuevo_id_cita()
    print(f"Nuevo ID de cita: {cita_id}")
    
    # Agregar la cita a la hoja agenda_worksheet
    first_empty_row = len(agenda_worksheet.get_all_values()) + 1
    agenda_worksheet.update_cell(first_empty_row, 1, cita_id)  # ID de la cita
    agenda_worksheet.update_cell(first_empty_row, 2, medico)  # Médico
    agenda_worksheet.update_cell(first_empty_row, 3, especialidad)  # Especialidad
    agenda_worksheet.update_cell(first_empty_row, 4, name)  # Nombre paciente
    agenda_worksheet.update_cell(first_empty_row, 5, dni)  # DNI del paciente
    agenda_worksheet.update_cell(first_empty_row, 6, fecha)  # Fecha
    agenda_worksheet.update_cell(first_empty_row, 7, hora)  # Hora
    
    result_message = f"Cita agendada con éxito para el médico {medico} en la especialidad {especialidad} el {fecha} a las {hora}."
    print(result_message)
    return result_message

def consultar_disponibilidad(params):
    """
    Consulta las fechas y horas disponibles para una especialidad o médico en un rango de fechas específico.

    :param params: Diccionario que debe contener los siguientes campos:
        - 'tipo' (str): Indica 'especialidad' si se especifica una especialidad médica, o 'médico' si se proporciona el nombre de un médico. Ejemplo: "especialidad".
        - 'identificador' (str): Dependiendo del tipo de consulta, especifica la especialidad médica o el nombre del médico. Ejemplo: "Dermatología".
        - 'fecha_inicio' (str): Fecha de inicio del rango en formato YYYY-MM-DD. Ejemplo: "2024-06-01".
        - 'fecha_fin' (str, opcional): Fecha de fin del rango en formato YYYY-MM-DD. Si no se proporciona, se considera igual a la fecha de inicio. Ejemplo: "2024-06-30".
    :return: Diccionario con las fechas y horas disponibles, en el siguiente formato:
        {
            'YYYY-MM-DD': [lista de horas disponibles],
            ...
        }
        O un diccionario con un mensaje de error si ocurre algún problema. Ejemplo:
        {"error": "Formato de fecha inválido: time data '2024-06-31' does not match format '%Y-%m-%d'."}
    """

    print(f"Entrando en la función consultar_disponibilidad con params: {params}")

    tipo = params.get('tipo')
    fecha_inicio = params.get('fecha_inicio')
    fecha_fin = params.get('fecha_fin')
    identificador = params.get('identificador')  # Puede ser especialidad o nombre del médico

    # Conversión de las fechas desde formato de cadena a objetos datetime
    try:
        fecha_inicio_dt = datetime.datetime.strptime(fecha_inicio, '%Y-%m-%d')
        # Si fecha_fin no se proporciona, la fecha_fin es igual a la fecha_inicio
        if fecha_fin is None:
            fecha_fin_dt = fecha_inicio_dt
        else:
            fecha_fin_dt = datetime.datetime.strptime(fecha_fin, '%Y-%m-%d')
    except ValueError as e:
        return {"error": f"Formato de fecha inválido: {e}"}
    
    # Verificación de que la fecha de inicio no sea posterior a la fecha de fin
    if fecha_inicio_dt > fecha_fin_dt:
        return {"error": "La fecha de inicio no puede ser posterior a la fecha de fin."}
    
    disponibilidad = {}

    fecha_actual = fecha_inicio_dt
    while fecha_actual <= fecha_fin_dt:
        fecha_str = fecha_actual.strftime('%Y-%m-%d')
        # Llamada a la función que verifica la disponibilidad para una fecha específica
        horas_disponibles, mensaje_error = verificar_disponibilidad(fecha_str, None, identificador, tipo)
        
        if mensaje_error:
            return {"error": mensaje_error}
        
        if horas_disponibles:
            disponibilidad[fecha_str] = horas_disponibles
        
        fecha_actual += datetime.timedelta(days=1)
    
    return disponibilidad

def enviar_disponibilidad_con_botones(update: Update, context: CallbackContext, disponibilidad):
    # Verificar si el argumento es una cadena JSON y convertirlo a un diccionario
    if isinstance(disponibilidad, str):
        try:
            disponibilidad = json.loads(disponibilidad)
        except json.JSONDecodeError:
            context.bot.send_message(chat_id=update.message.chat_id, text="Error al procesar la disponibilidad.")
            return

    keyboard = []
    row = []
    button_count = 0
    for fecha, horas in disponibilidad.items():
        fecha_button = InlineKeyboardButton(fecha, callback_data=fecha)
        row.append(fecha_button)
        button_count += 1

        if button_count % 3 == 0:
            keyboard.append(row)
            row = []

        for hora in horas:
            hora_button = InlineKeyboardButton(hora, callback_data=f"{fecha}:{hora}")
            row.append(hora_button)
            button_count += 1

            if button_count % 3 == 0:
                keyboard.append(row)
                row = []

    # Añadir la última fila si no está vacía
    if row:
        keyboard.append(row)

    reply_markup = InlineKeyboardMarkup(keyboard)
    context.bot.send_message(chat_id=update.message.chat_id, text="Selecciona una fecha y hora:", reply_markup=reply_markup)


def cancelar_cita(params):
    """
    Elimina una cita agendada del usuario.

    :param params: Diccionario con parámetros necesarios para identificar la cita.
                   Debe incluir 'dni', y puede incluir 'cita_id', 'fecha' y 'hora'.
    :return: Mensaje de confirmación o error.
    """
    print(f"Entrando en la función cancelar_cita con params: {params}")

    cita_id = params.get('cita_id')
    dni = params.get('dni')
    fecha = params.get('fecha')
    hora = params.get('hora')

    if not dni:
        return "El DNI del paciente es obligatorio."

    # Obtener todas las filas de la hoja agenda_worksheet
    all_rows = agenda_worksheet.get_all_values()

    # Buscar el nombre del paciente usando el DNI
    paciente_encontrado = False
    nombre_paciente = None
    cita_eliminada = None

    for row in all_rows:
        if row[4] == dni:
            nombre_paciente = row[3] 
            paciente_encontrado = True
            break

    if not paciente_encontrado:
        return f"No se encontró un paciente con el DNI {dni}."

    if cita_id:
        # Buscar y eliminar la cita por ID
        for idx, row in enumerate(all_rows):
            if row[0] == str(cita_id) and row[4] == dni:
                # Guardar detalles de la cita antes de eliminarla
                cita_eliminada = {
                    'medico': row[1],
                    'especialidad': row[2],
                    'fecha': row[5],
                    'hora': row[6]
                }
                agenda_worksheet.delete_rows(idx + 1)
                return f"Cita de {nombre_paciente} (DNI: {dni}) con ID {cita_id} eliminada con éxito.\n" \
                        f"Detalles de la cita:\n" \
                        f"Médico: {cita_eliminada['medico']}\n" \
                        f"Especialidad: {cita_eliminada['especialidad']}\n" \
                        f"Fecha: {cita_eliminada['fecha']}\n" \
                        f"Hora: {cita_eliminada['hora']}"
            
        return f"No se encontró una cita con ID {cita_id} para el paciente {nombre_paciente}."
    else:
        # Verificar que se proporcionen 'fecha' y 'hora' si no se proporciona 'cita_id'
        if not (fecha and hora):
            return "Debe proporcionar 'fecha' y 'hora' si no se proporciona 'cita_id'."
        
        # Buscar y eliminar la cita por los datos del paciente
        for idx, row in enumerate(all_rows):
            if row[4] == dni and row[5] == fecha and row[6] == hora:
                # Guardar detalles de la cita antes de eliminarla
                cita_eliminada = {
                    'cita_id': row[0],
                    'medico': row[1],
                    'especialidad': row[2],
                }
                agenda_worksheet.delete_rows(idx + 1)
                return f"Cita de {nombre_paciente} (DNI: {dni}) el {fecha} a las {hora} eliminada con éxito.\n" \
                        f"Detalles de la cita:\n" \
                        f"ID de la cita: {cita_eliminada['cita_id']}\n" \
                        f"Médico: {cita_eliminada['medico']}\n" \
                        f"Especialidad: {cita_eliminada['especialidad']}"
        return f"No se encontró una cita para {nombre_paciente} (DNI: {dni}) el {fecha} a las {hora}."

def consultar_citas_agendadas(params):
    """
    Consulta las citas agendadas para un usuario en un periodo específico.

    :param params: Diccionario con los parámetros necesarios:
                   - 'dni': DNI del paciente (obligatorio).
                   - 'fecha_inicio': Fecha de inicio del periodo en formato YYYY-MM-DD (opcional).
                   - 'fecha_fin': Fecha de fin del periodo en formato YYYY-MM-DD (opcional).
    :return: Mensaje con las citas encontradas o un mensaje de error.
    """
    print(f"Entrando en la función consultar_citas_agendadas con params: {params}")

    dni = params.get('dni')
    fecha_inicio = params.get('fecha_inicio')
    fecha_fin = params.get('fecha_fin')

    if not dni:
        return "El DNI del paciente es obligatorio."

    try:
        fecha_inicio_dt = datetime.datetime.strptime(fecha_inicio, '%Y-%m-%d') if fecha_inicio else None
        fecha_fin_dt = datetime.datetime.strptime(fecha_fin, '%Y-%m-%d') if fecha_fin else None
    except ValueError as e:
        return f"Formato de fecha inválido: {e}"

    # Si fecha_fin no se proporciona, se usa fecha_inicio como fecha_fin
    if fecha_inicio_dt and not fecha_fin_dt:
        fecha_fin_dt = fecha_inicio_dt

    if fecha_inicio_dt and fecha_fin_dt and fecha_inicio_dt > fecha_fin_dt:
        return "La fecha de inicio no puede ser posterior a la fecha de fin."

    # Obtener todas las filas de la hoja agenda_worksheet
    all_rows = agenda_worksheet.get_all_values()

    citas = []

    for row in all_rows:
        if row[4] == dni:
            fecha_cita = datetime.datetime.strptime(row[5], '%Y-%m-%d')
            if (fecha_inicio_dt is None or fecha_cita >= fecha_inicio_dt) and (fecha_fin_dt is None or fecha_cita <= fecha_fin_dt):
                citas.append({
                    'cita_id': row[0],
                    'medico': row[1],
                    'especialidad': row[2],
                    'fecha': row[5],
                    'hora': row[6]
                })

    if citas:
        citas_str = "\n".join(
            f"Cita ID: {cita['cita_id']}, Médico: {cita['medico']}, Especialidad: {cita['especialidad']}, Fecha: {cita['fecha']}, Hora: {cita['hora']}"
            for cita in citas
        )
        return f"Tus citas agendadas:\n{citas_str}"
    else:
        return "No se encontraron citas para el DNI proporcionado en el periodo especificado."



def wait_on_run(run, thread):
    while run.status == "queued" or run.status == "in_progress":
        run = client.beta.threads.runs.retrieve(
            thread_id=thread.id,
            run_id=run.id,
        )
        time.sleep(0.5)
    return run

class EventHandler(AssistantEventHandler):
    @override
    def on_text_created(self, text) -> None:
        print(f"\nassistant > ", end="", flush=True)

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
                print(f"\n\noutput >", flush=True)
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

def handle_message(update: Update, context: CallbackContext):
    telegram_id = update.message.chat_id
    text = update.message.text

    # Enviar acción de "escribiendo..."
    context.bot.send_chat_action(chat_id=telegram_id, action=ChatAction.TYPING)

    if not get_thread_id(telegram_id):
        thread = client.beta.threads.create()
        set_thread_id(telegram_id, thread.id)
        set_first_msg_id(telegram_id, None)
    else:
        thread_id = get_thread_id(telegram_id)
        thread = client.beta.threads.retrieve(thread_id)
        print(f"Retrieved thread: {thread_id}")

    try:
        message = client.beta.threads.messages.create(
            thread_id=get_thread_id(telegram_id),
            role="user",
            content=text
        )
        print(f"Created message: {message}")
    except Exception as e:
        print(f"Error creating message: {e}")
        return

    thread_id = get_thread_id(telegram_id)
    first_msg_id = get_first_msg_id(telegram_id)

    try:
        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=assistant.id
        )
        print(f"Run status: {run.status}")
    except Exception as e:
        print(f"Error creating and polling run: {e}")
        return
    
    if run.status == 'requires_action':

        print (">>> Entrando a requires_action")
        tool_call = run.required_action.submit_tool_outputs.tool_calls[0]
        name = tool_call.function.name
        arguments = json.loads(tool_call.function.arguments)
        respuesta_funcion = globals().get(name)
    
        print ("Argumentos recibidos:")
        print(arguments)

        if not respuesta_funcion:
            print(f"No function named {name} found.")
            return

        if name == "consultar_disponibilidad":
            result = consultar_disponibilidad(arguments)
            ##if isinstance(result, dict):
                # No convertir el resultado a JSON aquí
            ##    enviar_disponibilidad_con_botones(update, context, result)  # Pasar el diccionario directamente
            ##else:
                # Manejar el caso en que result no sea un diccionario
                ##context.bot.send_message(chat_id=telegram_id, text=result)
        elif name == "cancelar_cita":
            result = cancelar_cita(arguments)
        elif name == "consultar_citas_agendadas":
            result = consultar_citas_agendadas(arguments)
        else:
            result = agendar_cita(arguments)
        
        print("Resultado tras ejecutar la función:")
        print(result)


        # Convertir el resultado a cadena de texto si no lo es
        if isinstance(result, dict):
            result = json.dumps(result)  # Convertir diccionario a cadena JSON
        elif not isinstance(result, str):
            result = str(result)


        # Enviar el resultado de la llamada a la función
        try:
            run = client.beta.threads.runs.submit_tool_outputs(
                thread_id=thread_id,
                run_id=run.id,
                tool_outputs=[
                    {"tool_call_id": tool_call.id, "output": result}
                ],
            )
            #print(f"Tool outputs submitted: {run}")
        except Exception as e:
            print(f"Error submitting tool outputs: {e}")
            return

        # Mostrar información de depuración
        show_json(run)
        
        # Esperar a que el run se complete
        run = wait_on_run(run, thread)
       
    try:
         # Listar los mensajes en el hilo
        messages = client.beta.threads.messages.list(thread_id, before=first_msg_id)
    except Exception as e:
        print(f"Error listing messages: {e}")
        return

    set_first_msg_id(telegram_id, messages.first_id)

    for m in messages.data:
        if m.role == 'assistant':
            context.bot.send_message(chat_id=telegram_id, text=m.content[0].text.value)

def handle_location(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    context.bot.send_message(chat_id=chat_id, text="Recibí tu ubicación.")

def handle_photo(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    photo_file = update.message.photo[-1].get_file()
    photo_url = photo_file.file_path

    user_message = update.message.caption if update.message.caption else "Para qué sirve este medicamento?"
    user_message += " Ayudas a los usuarios proporcionándoles información breve y precisa sobre medicamentos de la base de datos de tu conocimiento para proporcionar de forma resumida el propósito y las instrucciones de uso, y haciendo hincapié en la obligatoriedad de la prescripción médica para aquellos medicamentos que así estén prescritos. En caso de que se solicite información sobre un medicamento que requiera prescripción médica, proporcionando información sobre el doctor del Hospital Clínico más apropiado para consultarle, y pregunta si desea agendar una cita médica con el mismo. Importante si el medicamento no es conocido, indica de forma amable que no lo conoces y sugiere consultar con un profesional."

    print(f"URL de la imagen: {photo_url}")

    context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_message},
                    {"type": "image_url", "image_url": {"url": photo_url}},
                ],
            }
        ],
        max_tokens=300,
    )

    try:
        content = response.choices[0].message.content
        print(f"Contenido de la imagen: {content}")
        context.bot.send_message(chat_id=chat_id, text=content)
    except Exception as e:
        print(f"Error al procesar la imagen: {e}")
        context.bot.send_message(chat_id=chat_id, text="No se pudo obtener el contenido de la imagen.")

def main():
    updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    dispatcher.add_handler(MessageHandler(Filters.location, handle_location))
    dispatcher.add_handler(MessageHandler(Filters.photo, handle_photo))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
