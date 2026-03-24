"""Template engine for documentation."""

from jinja2 import Environment, FileSystemLoader

class TemplateEngine:
    """Renders documentation from templates."""
    
    def __init__(self, template_dir: str):
        self.env = Environment(loader=FileSystemLoader(template_dir))
    
    def render(self, template_name: str, context: dict) -> str:
        """Render template with context.
        
        Args:
            template_name: Name of template file
            context: Context variables
        
        Returns:
            Rendered template
        """
        template = self.env.get_template(template_name)
        return template.render(**context)
