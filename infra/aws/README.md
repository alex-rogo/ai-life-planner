# Put AI Planner online

This setup creates one small Amazon Lightsail server. The website, API, and database all run on that server, and its address stays the same when it restarts.

The default server costs about $12 per month. AWS bills by the hour up to that monthly amount. No load balancer or separate database service is used.

## Deploy

You need an AWS account, Terraform 1.8 or newer, and AWS credentials configured on your computer.

From the repository root in PowerShell:

```powershell
.\scripts\deploy-aws.ps1
```

Review the AWS changes and enter `yes`. The first setup normally takes several minutes because the server installs the app and builds it. The script prints the web address, username, and generated password.

The address uses a free `sslip.io` hostname so the site can use HTTPS without buying a domain. Save the password somewhere private.

## Update the app

Open the Lightsail browser terminal for the `ai-planner` server and run:

```bash
cd /opt/ai-planner/source
sudo git pull
sudo docker compose --env-file .env.production -f docker-compose.production.yml up -d --build
```

The database is kept in a persistent volume and is not replaced during updates.

## Gemini

The deployed app starts in demo mode. To enable Gemini, edit `/opt/ai-planner/source/.env.production` on the server, set `AI_MODE=gemini` and add `GEMINI_API_KEY`, then run the update command above.

## Remove it

From `infra/aws` run `terraform destroy`. This permanently deletes the server and its stored planner data.
