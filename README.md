# Smart Crop Backend

## Run app in docker:

* Build docker image with the command:

`docker build -t smart-crop-advisor .`

* Run the docker image:
`docker run -p 5000:5000 smart-crop-advisor`

## Test

You cat test whether the app is up and running by calling the endpoint below using curl:
`curl http://127.0.0.1:5000/api/advisor/health`

> **Note:** You can also use postman to call the endpoint 

## Keys to be configured:

```
SECRET_KEY=supersecretkey
DATABASE_URL=sqlite:///crop_advisor.db
OPENAI_API_KEY=api-key
WEATHER_API_KEY=weather-api-key
```
