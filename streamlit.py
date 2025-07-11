import pathlib
import streamlit as st
from openai import OpenAI
import time

# Initialize OpenAI client
client = OpenAI()
model = "gpt-4o-mini"

# Function to create a new vector store and upload files
def create_vector_store(file_streams):
    vector_store = client.vector_stores.create(name="Corpus")
    client.vector_stores.file_batches.upload_and_poll(
        vector_store_id=vector_store.id, files=file_streams
    )
    return vector_store

# Function to add files to an existing vector store
def add_files_to_vector_store(vector_store_id, files):
    file_streams = [(file.name, file) for file in files]
    batch = client.vector_stores.file_batches.upload_and_poll(
        vector_store_id=vector_store_id, files=file_streams
    )
    return batch

# Function to get assistant response with citations
def get_assistant_response(assistant, input_text, thread_id):
    message = client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=input_text
    )

    run = client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=assistant.id,
    )

    # Wait for the run to complete
    while True:
        run_status = client.beta.threads.runs.retrieve(
            thread_id=thread_id,
            run_id=run.id
        )
        if run_status.status == 'completed':
            break
        elif run_status.status in ['failed', 'cancelled', 'expired']:
            print(f"Run failed with status: {run_status.status}")
            return None, []
        time.sleep(1)

    # Get most recent message
    messages = client.beta.threads.messages.list(
        thread_id=thread_id,
        order="desc",
        limit=1
    )

    latest_message = messages.data[0]
    if latest_message.role != "assistant" or latest_message.run_id != run.id:
        return None, []

    content_part = latest_message.content[0].text
    full_text = content_part.value
    annotations = content_part.annotations

    file_id_to_index = {}
    citations = []
    citation_counter = 0

    for annotation in annotations:
        file_citation = getattr(annotation, "file_citation", None)
        if file_citation:
            file_id = file_citation.file_id

            # Assign a unique number per file
            if file_id not in file_id_to_index:
                cited_file = client.files.retrieve(file_id)
                file_index = citation_counter
                file_id_to_index[file_id] = file_index
                citations.append(f"[{file_index}] {cited_file.filename}")
                citation_counter += 1
            else:
                file_index = file_id_to_index[file_id]

            # Replace the annotated text with consistent citation index
            full_text = full_text.replace(annotation.text, f"[{file_index}]", 1)

    return full_text, citations


# Initialize session state
for key in ['assistant', 'thread_id', 'messages', 'files_uploaded', 'vector_store', 'uploaded_file_names']:
    if key not in st.session_state:
        st.session_state[key] = [] if key == 'messages' else set() if key == 'uploaded_file_names' else None


#  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ FILL IN YOUR APP TITLE AND SUBHEADER BELOW ~~~~~~~~~~~~~~~~~~
st.title("Libra Clothing") # TO-D0 - FILL IN YOUR APP TITLE
st.subheader("Find your style") # TO-D0 - FILL IN YOUR APP SUBHEADER - What message should the user see first?

def list_pdfs(folder:str):
    p = pathlib.Path(folder)
    return sorted(p.glob("*pdf")) if p.is_dir() else()

folder = "./context"
pdf_paths = list_pdfs(folder)
uploaded_files = [file for file in pdf_paths if file.name not in st.session_state.uploaded_file_names]


if uploaded_files:
    file_streams = [(p.name, p.open('rb')) for p in uploaded_files]


    if st.session_state.vector_store is None:
        st.session_state.vector_store = create_vector_store(file_streams)
    else:
        add_files_to_vector_store(st.session_state.vector_store.id, file_streams)

    st.session_state.uploaded_file_names.update(file.name for file in uploaded_files)
    st.success(f"Uploaded {len(uploaded_files)} new file(s).")

# ~~~~~~~~~~~~~~~~~~~~~~~~~~ CREATE YOUR ASSISTANT BELOW ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    # Create assistant if it doesn't exist
    if st.session_state.assistant is None:
        st.session_state.assistant = client.beta.assistants.create( ## TO-DO - FILL IN YOUR ASSISTANT NAME, INSTRUCTIONS, AND TOOLS
            name="Libra",
            instructions="You are going to help me find the most affordable clothing, brands, high-quality, and nice clothing. Along with that, you are going to help me in forming my non-profit to give kids who live in harsh conditions free clothing.",
            model=model,
            tools=[{"type": "file_search"}], # FILL IN: What tool does the assistant need to efficiently search files using the vector store?
        )

    # Update assistant's vector store connection
    client.beta.assistants.update(
        assistant_id=st.session_state.assistant.id,
        tool_resources={"file_search": {"vector_store_ids": [st.session_state.vector_store.id]}}
    )

    # Create thread if it doesn't exist
    if st.session_state.thread_id is None:
        thread = client.beta.threads.create()
        st.session_state.thread_id = thread.id

    # # Show uploaded files
    # st.write("Uploaded files:")
    # for file in uploaded_files:
    #     st.write(f"• {file.name}")

    st.session_state.files_uploaded = True

# Display conversation history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "citations" in msg and msg["citations"]:
            st.write("Citations:")
            for c in msg["citations"]:
                st.write(f"- {c}")

# Chat input
if st.session_state.files_uploaded:
    if user_input := st.chat_input("Ask a question about your files..."):
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                reply, citations = get_assistant_response(
                    st.session_state.assistant,
                    user_input,
                    st.session_state.thread_id
                )

            st.markdown(reply)
            if citations:
                st.write("Citations:")
                for c in citations:
                    st.write(f"- {c}")

            st.session_state.messages.append({
                "role": "assistant",
                "content": reply,
                "citations": citations
            })

# Clear conversation
if st.session_state.messages:
    if st.button("Clear Conversation"):
        st.session_state.messages = []
        st.session_state.thread_id = client.beta.threads.create().id
        st.rerun()