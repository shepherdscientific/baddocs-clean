# GitHub App Setup

## Creating a GitHub App

1. Go to https://github.com/settings/apps
2. Click "New GitHub App"
3. Fill in the required fields:
   - **GitHub App name**: BadDocs
   - **Homepage URL**: https://example.com
   - **Webhook URL**: https://your-domain.com/webhook
   - **Webhook secret**: Generate a secure secret

## Permissions

Required permissions:
- **Repository**: 
  - Contents (read)
  - Metadata (read)
  - Pull requests (read)
- **Organization**:
  - Members (read)

## Events to Subscribe

- Push
- Pull request
- Repository

## Installation

1. Generate a private key
2. Note the App ID
3. Configure BadDocs with these credentials
