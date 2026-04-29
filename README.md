# Smart Crop Backend

## Run app using docker compose:

`docker-compose up --build`

## Test

You can test whether the app is up and running by calling the endpoint below using curl:
`curl http://127.0.0.1:5000/api/advisor/health`

> **Note:** You can also use postman to call the endpoint 

## Available endpoints (swagger)

You can access Swagger API documentation by following the link in the browser:
`http://localhost:5000/apidocs/`

## Keys to be configured:

```
SECRET_KEY=supersecretkey
DATABASE_URL=postgresql://postgres:123@localhost:5433/smartcrop
OPENAI_API_KEY=api-key
WEATHER_API_KEY=weather-api-key
JWT_SECRET_KEY=6d4b9f10199947df8cbfe393cc6d6a81
LOG_LEVEL=INFO
```
