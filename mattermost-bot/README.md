# Bot with slash command

## 사전 가입 필요

1. ngrok 가입 <br>
https://dashboard.ngrok.com/signup <br>
https://dashboard.ngrok.com/get-started/your-authtoken <br>

  - 생성된 토큰을 셋팅한다 <br>
ngrok config add-authtoken $YOUR_AUTHTOKEN

- <b>(Info)</b> 왜 ngrok를 써야 하나요? <br>
ngrok는 로컬에 떠 있는 python 서버를 K8S에 설치된 Mattermost에서도 접근할 수 있게 URL을 포워딩해준다. K8S 상의 POD에서 "http://localhost:8999"를 접근하려고하면 POD 자체에 떠있는 Application의 URL로 인식하기 때문임임   

<br>

2. OpenAI API platform에 가입하고 사용 비용을 사전에 충전해야한다. <br>
https://platform.openai.com/
- API 토큰을 발급 받아 .env에 셋팅한다. <br>
  (API 토근은 절대 github에 올라가지 않게 조심해야함)
<br><br>

## 환경 셋팅
1. 가상 환경 셋팅
   VS Code 가상환경 셋팅 방법 참조 (KTDS_GPT_DEMO 폴더 상에서 설정)<br>
   https://www.ecopro.ai/entry/Visual-Studio-Code-%ED%8C%8C%EC%9D%B4%EC%8D%ACPython-%EA%B0%80%EC%83%81%EA%B0%9C%EB%B0%9C%ED%99%98%EA%B2%BDvenv-%EC%84%A4%EC%A0%95

2. 라이브러리 설치
pip install -r requirements.txt
<br>

## 실행
1. 터미널창에서 python 실행
cd mattermost-bot<br>
uvicorn main:app --reload --port 8999

2. ngrok 실행
- ngrok http 8999
- Forwarding URL을 Mattermost Slash Commands의 Request URL에 셋팅<br>
  ex) https://bb38-121-138-201-117.ngrok-free.app/webhook
- http://127.0.0.1:4040/ 에서 현재 트래픽과 로그 확인 가능

<br>

## 사용법
채널에서 "/gpt help"를 치면 사전에 지정된 답변이 도출된다. <br>
"/gpt 한국의 사계절에 대해 알려줘" <br>
이런식의 문장은 사전 등록이 안되어 있기에 GPT로 전달되고 GPT에 의해 생성된 답변을 받을 수 있다.


