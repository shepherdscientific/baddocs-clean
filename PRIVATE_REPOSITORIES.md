# Private Repository Support

## Accessing Private Repositories

### GitHub Token Setup

1. Create a GitHub token with `repo` scope
2. Set `GITHUB_TOKEN` environment variable
3. BadDocs will automatically use the token for private repository access

### SSH Key Setup

1. Add your SSH key to the system
2. BadDocs will use SSH URLs for repository cloning

## Security Considerations

- Keep tokens secure
- Use fine-grained tokens when possible
- Regularly rotate credentials
