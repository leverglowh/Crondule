# Crondule
This is a telegram bot that can send scheduled and cronned messages.\
To use this checkout https://t.me/crondulebot

## Usage
### Initialize bot
Use the `/settimezone` command to set your timezone.\
If none is provided, UTC is used (Europe/London +0).

### Schedule a message
Use the `/schedule` command to schedule a message.\
You will be prompted to input a desired date time in the `YYYY-MM-DD HH:MM` format.

Example: `2025-12-31 04:52` is December 31st at 04:52 AM.

The bot will then confirm to you in how many minutes the message will be sent, and ask you to input your message.

### Cron a message
Use the `/cron` command to configure a recurrent message.\
You will be prompted to input a [cron syntax](https://en.wikipedia.org/wiki/Cron#Overview) schedule.

You can use https://it-tools.tech/crontab-generator to help you compose it.

The bot will then ask you to input your message.

A message will confirm the schedule.

### List jobs
Use the `/list` command to list scheduled messages.

### Delete jobs
Use the `/delete job_id` command to delete a schedules message.

Example: `/delete 12345566778`

## Self Hosted
You can self host the bot by using this docker compose
```yaml
services:
  crondule:
    container_name: crondule
    image: ghcr.io/leverglowh/crondulebot:latest
    restart: unless-stopped
    environment:
      - BOT_TOKEN=your_bot_token # Get it from bot father
    volumes:
      - ./data:/app/data # To persist scheduled messages

```
