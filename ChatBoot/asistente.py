# Se importan las librerías
import streamlit as st
import os
from openai import OpenAI
from openai.types.beta.assistant_stream_event import ThreadMessageDelta
from openai.types.beta.threads.text_delta_block import TextDeltaBlock

# Clave API y ID del asistente
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASSISTANT_ID = "asst_7fJG6LWLdcFsMg51LCcm1cvY"

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
