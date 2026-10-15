"""Aira's Streamlit dashboard. All data stays in the local SQLite database."""
import streamlit as st

from aira.api import create_app
from aira.faq import FAQService
from aira.repository import Repository
from aira.urgency import classify_urgency

st.set_page_config(page_title="Aira Receptionist", page_icon="👋", layout="wide")
st.markdown("""
<style>
.stApp { background: #0b1220; color: #e5edf8; }
[data-testid="stSidebar"] { background: #101a2c; }
[data-testid="stMetric"] { background: #132036; padding: 1rem; border: 1px solid #263752; border-radius: 12px; }
.block-container { max-width: 1320px; padding-top: 2rem; }
</style>
""", unsafe_allow_html=True)

backend = create_app()
repo: Repository = backend.state.repository
receptionist = backend.state.receptionist
faq_service: FAQService = backend.state.faq_service

st.title("👋 Aira Receptionist")
st.caption("A local, rule-based receptionist dashboard. Customer data is stored in a local SQLite file.")

tabs = st.tabs(["Receptionist", "Messages", "Customers", "Escalations", "FAQs"])

with tabs[0]:
    st.header("Welcome")
    st.write("Welcome to our business. Ask about the information listed below, or leave a message for the owner.")
    faq_rows = faq_service.load()
    business_facts = {entry.get("category", "general"): entry["answer"] for entry in faq_rows}
    left, right = st.columns(2)
    with left:
        st.subheader("Business hours")
        st.write(business_facts.get("hours", "Hours have not been added to the local knowledge base."))
    with right:
        st.subheader("Services")
        st.write(business_facts.get("services", "Services have not been added to the local knowledge base."))

    st.subheader("Text chat")
    if "aira_customer_id" not in st.session_state:
        st.session_state.aira_customer_id = None
        st.session_state.aira_conversation_id = None
        st.session_state.aira_chat_history = []
    for item in st.session_state.aira_chat_history:
        with st.chat_message(item["role"]):
            st.markdown(item["text"])
    user_text = st.chat_input("Ask a question or describe what you need")
    if user_text:
        result = receptionist.respond(
            user_text, customer_id=st.session_state.aira_customer_id,
            conversation_id=st.session_state.aira_conversation_id, source="chat",
        )
        st.session_state.aira_customer_id = result["customer_id"]
        st.session_state.aira_conversation_id = result["conversation_id"]
        st.session_state.aira_chat_history.extend([
            {"role": "user", "text": user_text}, {"role": "assistant", "text": result["answer"]}
        ])
        st.rerun()

    st.subheader("Simulated incoming call")
    st.caption("Demonstration only. This does not place, receive, or record a real phone call.")
    with st.form("simulated_call_form"):
        call_transcript = st.text_area("Paste a sample caller transcript", key="call_transcript")
        call_sent = st.form_submit_button("Process simulated transcript")
    if call_sent and call_transcript.strip():
        result = receptionist.respond(call_transcript, source="simulated_call")
        st.success(f"Rule-based reply: {result['answer']}")
        st.caption(f"Priority: {result['priority']}. This transcript was processed as a simulation.")

    st.subheader("Leave a message")
    with st.form("contact_form", clear_on_submit=True):
        name = st.text_input("Your name")
        phone = st.text_input("Phone number")
        enquiry = st.text_area("Your enquiry")
        callback_time = st.text_input("Preferred callback time (optional)")
        confirmed = st.checkbox("I confirm these details and agree to save this message locally.")
        submitted = st.form_submit_button("Review and save message")
    if submitted:
        if not all((name.strip(), phone.strip(), enquiry.strip())):
            st.error("Please enter your name, phone number, and enquiry.")
        elif not confirmed:
            st.error("Please confirm the details before saving.")
        else:
            customer_id = repo.identify_or_create(name, phone)
            conversation_id = repo.create_conversation(customer_id, "contact_form")
            saved = repo.create_message(customer_id, enquiry, classify_urgency(enquiry), "contact_form",
                                        callback_time.strip() or None, conversation_id)
            st.success(f"Message saved. Reference: {saved['id']}")
            if saved["escalation_id"]:
                st.warning("This message needs human review. No notification was sent.")

with tabs[1]:
    st.header("Messages and conversations")
    search_col, status_col = st.columns([2, 1])
    with search_col:
        search = st.text_input("Search name, phone, or message")
    with status_col:
        status_filter = st.selectbox("Status", ["All", "new", "in_progress", "resolved"])
    messages = repo.list_messages(search, None if status_filter == "All" else status_filter)
    if not messages:
        st.info("No messages match this view yet.")
    for message in messages:
        with st.container(border=True):
            st.markdown(f"**{message['customer_name']}** · {message['phone'] or 'No phone'} · **{message['priority']}**")
            st.write(message["body"])
            st.caption(f"{message['created_at']} · {message['source']} · customer {message['customer_id']}")
            new_status = st.selectbox("Message status", ["new", "in_progress", "resolved"],
                                      index=["new", "in_progress", "resolved"].index(message["status"]),
                                      key=f"msg-status-{message['id']}")
            if new_status != message["status"] and st.button("Update status", key=f"msg-update-{message['id']}"):
                repo.update_message_status(message["id"], new_status)
                st.rerun()
            with st.expander("Correct or delete this message"):
                corrected_body = st.text_area("Enquiry", value=message["body"], key=f"msg-body-{message['id']}")
                corrected_callback = st.text_input("Preferred callback time", value=message["callback_time"] or "",
                                                   key=f"msg-callback-{message['id']}")
                edit_col, delete_col = st.columns(2)
                with edit_col:
                    if st.button("Save corrections", key=f"msg-edit-{message['id']}"):
                        if not corrected_body.strip():
                            st.error("The enquiry cannot be blank.")
                        else:
                            repo.edit_message(message["id"], corrected_body, corrected_callback or None,
                                              classify_urgency(corrected_body))
                            st.success("Message corrected and urgency rechecked.")
                            st.rerun()
                with delete_col:
                    if st.button("Delete message", key=f"msg-delete-{message['id']}"):
                        repo.delete_message(message["id"])
                        st.success("Message and its escalation record deleted.")
                        st.rerun()

with tabs[2]:
    st.header("Customer memory")
    customer_rows = repo.customers()
    if customer_rows:
        choices = {f"{c['name']} · {c['phone'] or 'no phone'} · {c['id'][-8:]} ": c for c in customer_rows}
        selected_label = st.selectbox("Select a customer", list(choices))
        customer = choices[selected_label]
        st.caption(f"Customer ID: {customer['id']} · Exact phone matches are only reused after owner verification.")
        if customer["phone"] and not customer["phone_verified"]:
            if st.button("Verify this phone number", key="verify-phone"):
                repo.verify_phone(customer["id"])
                st.success("Phone number marked as verified by the owner.")
                st.rerun()
        st.subheader("Conversation history")
        history = repo.customer_history(customer["id"]) or []
        if history:
            for record in history:
                st.write(f"**{record['created_at']} · {record['priority']} · {record['status']}**")
                st.write(record["body"])
        else:
            st.info("No messages on this customer record yet.")
        with st.expander("Correct customer details"):
            edit_name = st.text_input("Name", value=customer["name"], key="edit-customer-name")
            edit_phone = st.text_input("Phone", value=customer["phone"] or "", key="edit-customer-phone")
            if st.button("Save customer corrections"):
                repo.edit_customer(customer["id"], edit_name, edit_phone or None)
                st.success("Customer details updated.")
                st.rerun()
        if st.button("Delete this customer and stored history", type="secondary"):
            repo.delete_customer(customer["id"])
            st.success("Customer record and associated messages deleted.")
            st.rerun()
    else:
        st.info("Customer records will appear after the first chat or message.")

with tabs[3]:
    st.header("Escalation review")
    st.caption("High and critical items are stored for human review. Aira does not send notifications.")
    escalation_rows = repo.list_escalations()
    open_escalations = [e for e in escalation_rows if e["status"] != "resolved"]
    if open_escalations:
        st.error(f"{len(open_escalations)} escalation(s) need attention.")
    else:
        st.success("No open escalations.")
    for escalation in escalation_rows:
        with st.container(border=True):
            st.markdown(f"**{escalation['priority']} · {escalation['customer_name']} · {escalation['status']}**")
            st.write(escalation["body"])
            st.caption(escalation["reason"])
            buttons = st.columns(2)
            with buttons[0]:
                if escalation["status"] == "open" and st.button("Acknowledge", key=f"ack-{escalation['id']}"):
                    repo.update_escalation(escalation["id"], "acknowledged")
                    st.rerun()
            with buttons[1]:
                if escalation["status"] != "resolved" and st.button("Resolve", key=f"resolve-{escalation['id']}"):
                    repo.update_escalation(escalation["id"], "resolved")
                    st.rerun()

with tabs[4]:
    st.header("Local FAQ knowledge base")
    st.caption("Aira answers from this file only. Add accurate business details here; missing information gets a safe fallback.")
    for faq in faq_service.load():
        with st.container(border=True):
            st.markdown(f"**{faq['question']}** · {faq.get('category', 'general')}")
            st.write(faq["answer"])
    with st.form("faq_form"):
        faq_question = st.text_input("FAQ question")
        faq_category = st.text_input("Category", value="general")
        faq_answer = st.text_area("Approved answer")
        faq_submitted = st.form_submit_button("Add FAQ")
    if faq_submitted:
        if not faq_question.strip() or not faq_answer.strip():
            st.error("Enter both a question and an approved answer.")
        else:
            faq_service.add(faq_question, faq_answer, faq_category)
            st.success("FAQ added to the local knowledge base.")
            st.rerun()

with st.sidebar:
    st.header("Overview")
    metrics = repo.stats()
    st.metric("Conversations", metrics["conversations"])
    st.metric("Messages", metrics["messages"])
    st.metric("Unresolved messages", metrics["unresolved"])
    st.metric("Open high / critical alerts", metrics["urgent"])
    st.divider()
    if st.button("Load demo conversations"):
        samples = [
            ("Demo Visitor", "555-0101", "What time do you open on weekdays?"),
            ("Demo Customer", "555-0102", "I was charged twice and need help urgently."),
            ("Demo Caller", "555-0103", "A gas leak is in the building."),
        ]
        for sample_name, sample_phone, sample_text in samples:
            result = receptionist.respond(sample_text, name=sample_name, phone=sample_phone, source="demo")
        st.success("Demo conversations added. They use sample data.")
        st.rerun()
