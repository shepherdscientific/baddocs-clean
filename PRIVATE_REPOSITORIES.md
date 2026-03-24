# Working with Private Repositories

## GitHub Authentication

### Personal Access Token

1. Generate token at https://github.com/settings/tokens
2. Set environment variable: `GITHUB_TOKEN=your_token`
3. BadDocs will automatically use this for private repository access

### SSH Keys

1. Add public key to GitHub account
2. Configure SSH in git config
3. BadDocs will use SSH URLs automatically

## Private Repository Analysis

```bash
baddocs-cli analyze --repo https://github.com/user/private-repo
```

## Security Considerations

- Never commit credentials
- Use environment variables or secret management
- Rotate tokens regularly
- Audit access logs
