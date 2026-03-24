const core = require('@actions/core');
const github = require('@actions/github');

function run() {
  try {
    const repository = core.getInput('repository');
    const provider = core.getInput('provider');
    
    core.info(`Analyzing repository: ${repository}`);
    core.info(`Using provider: ${provider}`);
    
    core.setOutput('status', 'success');
  } catch (error) {
    core.setFailed(error.message);
  }
}

run();
