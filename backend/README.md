
1. env setting<br>
python -m venv chatbot

- On Windows: chatbot\Scripts\activate 
- On macOS: source chatbot/bin/activate <br>
- deactive
<br><br>
2. Install library <br>
pip install -r requirements.txt<br><br>


3. Run applications<br>
cd app<br>
uvicorn main:app --host 0.0.0.0 --port 8999 --reload<br>
<br>
cd bot<br>
python main.py<br>