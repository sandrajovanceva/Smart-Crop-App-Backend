# Smart Crop Backend

## Run app using docker compose:

`docker-compose up --build`

## Test

You can test whether the app is up and running by calling the endpoint below using curl:
`curl http://127.0.0.1:5000/api/advisor/health`

> **Note:** You can also use postman to call the endpoint 

Available endpoints:
``` 
curl -X POST http://127.0.0.1:5000/api/auth/register
    -H "Content-Type: application/json"
    -d '{
        "email": "test@gmail.com",
        "password": "pass1234!",
        "fullName": "John Doe"
    }'
```
```
curl -X POST http://127.0.0.1:5000/api/auth/login
    -H "Content-Type: application/json"
    -d '{
        "email": "test@gmail.com",
        "password": "pass1234!"
    }'
```

```
curl -X POST http://127.0.0.1:5000/api/auth/logout 
    -H "Authorization: Bearer <access-token>"
```

```
curl -X GET http://127.0.0.1:5000/api/auth/me 
    -H "Authorization: Bearer <access-token>"
```

## Keys to be configured:

```
SECRET_KEY=supersecretkey
DATABASE_URL=postgresql://postgres:123@localhost:5433/smartcrop
OPENAI_API_KEY=api-key
WEATHER_API_KEY=weather-api-key
JWT_SECRET_KEY=6d4b9f10199947df8cbfe393cc6d6a81
```
