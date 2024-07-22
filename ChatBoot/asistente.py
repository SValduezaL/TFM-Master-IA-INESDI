# Se importan las librerías
import streamlit as st
import os
import requests
from openai import OpenAI
from openai.types.beta.assistant_stream_event import ThreadMessageDelta
from openai.types.beta.threads.text_delta_block import TextDeltaBlock

# Clave API y ID del asistente
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASSISTANT_ID = "asst_7fJG6LWLdcFsMg51LCcm1cvY"
BASE_URL = "https://hook.us1.make.com"

# Inicializar el cliente de OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

# Inicializar el estado de sesión para almacenar el historial de conversaciones localmente
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# Título de la aplicación
st.title("Asistente de Citas Médicas")

# Mostrar mensajes en el historial de chat
for message in st.session_state.chat_history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Definir las funciones para interactuar con la API
def consultar_informacion_dia_especialidad(dia, especialidad):
    url = f"{BASE_URL}/gy0wt4foj34pc8gnzeaxjeu685uikfe6"
    payload = {
        "dia": dia,
        "especialidad": especialidad
    }
    response = requests.post(url, json=payload)
    return response.json()

def consultar_informacion_dni(DNI):
    url = f"{BASE_URL}/5evvj26mthdd97mvj3swqydav2g5trqi"
    payload = {
        "DNI": DNI
    }
    response = requests.post(url, json=payload)
    return response.json()

def consultar_proxima_hora(especialidad=None):
    url = f"{BASE_URL}/zi6xcpjdxnpi94lqabo7uf74jytqr082"
    payload = {
        "especialidad": especialidad
    }
    response = requests.post(url, json=payload)
    return response.json()

def consultar_proxima_hora_especialidad(especialidad):
    url = f"{BASE_URL}/lb7e5btm9mrbhbf0efjg6xq62r6kskvf"
    payload = {
        "especialidad": especialidad
    }
    response = requests.post(url, json=payload)
    return response.json()

def agendar_cita(fecha, hora, especialidad, name, dni, medico=None):
    url = f"{BASE_URL}/bmlisnl39nlhu81jsvfrgzhxwh70sgo5"
    payload = {
        "fecha": fecha,
        "hora": hora,
        "especialidad": especialidad,
        "name": name,
        "dni": dni,
        "medico": medico
    }
    response = requests.post(url, json=payload)
    return response.json()

# Cuadro de texto y proceso de transmisión
if user_query := st.chat_input("Escribe un mensaje..."):

    # Crear un nuevo hilo si no existe
    if "thread_id" not in st.session_state:
        thread = client.beta.threads.create()
        st.session_state.thread_id = thread.id

    # Mostrar la consulta del usuario
    with st.chat_message("user"):
        st.markdown(user_query)

    # Almacenar la consulta del usuario en el historial
    st.session_state.chat_history.append({"role": "user", "content": user_query})
    
    # Agregar la consulta del usuario al hilo
    client.beta.threads.messages.create(
        thread_id=st.session_state.thread_id,
        role="user",
        content=user_query
    )

    # Transmitir la respuesta del asistente
    with st.chat_message("assistant"):
        stream = client.beta.threads.runs.create(
            thread_id=st.session_state.thread_id,
            assistant_id=ASSISTANT_ID,
            stream=True
        )
        
        # Contenedor vacío para mostrar la respuesta del asistente
        assistant_reply_box = st.empty()
        
        # Cadena en blanco para almacenar la respuesta del asistente
        assistant_reply = ""

        # Iterar a través del stream
        for event in stream:
            # Considerar solo si hay un delta de texto
            if isinstance(event, ThreadMessageDelta):
                if event.data.delta.content and isinstance(event.data.delta.content[0], TextDeltaBlock):
                    # Vaciar el contenedor
                    assistant_reply_box.empty()
                    # Agregar el nuevo texto
                    assistant_reply += event.data.delta.content[0].text.value
                    # Mostrar el nuevo texto
                    assistant_reply_box.markdown(assistant_reply)
        
        # Una vez que el stream haya terminado, actualizar el historial del chat
        st.session_state.chat_history.append({"role": "assistant", "content": assistant_reply})

        # Procesar la respuesta del asistente para llamadas a funciones
        if "consultar_informacion_dia_especialidad" in user_query:
            # Aquí deberías extraer los parámetros necesarios de la consulta del usuario
            resultado = consultar_informacion_dia_especialidad(dia="2024-06-10", especialidad="Cardiología")
            st.write(resultado)
        elif "consultar_informacion_dni" in user_query:
            # Aquí deberías extraer los parámetros necesarios de la consulta del usuario
            resultado = consultar_informacion_dni(DNI="12345678-9")
            st.write(resultado)
        elif "consultar_proxima_hora" in user_query:
            resultado = consultar_proxima_hora()
            st.write(resultado)
        elif "consultar_proxima_hora_especialidad" in user_query:
            resultado = consultar_proxima_hora_especialidad(especialidad="Cardiología")
            st.write(resultado)
        elif "agendar_cita" in user_query:
            resultado = agendar_cita(fecha="2024-06-15", hora="14:00", especialidad="Dermatología", name="Juan Pérez", dni="12345678-9")
            st.write(resultado)
