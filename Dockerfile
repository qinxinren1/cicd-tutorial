FROM node:22-slim

WORKDIR /app

COPY package.json .

RUN npm install -f

COPY . .

# EXPOSE 3001
EXPOSE 3001

CMD ["npm", "start"]