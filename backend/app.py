"""Flask application for Document Management Dashboard."""
from flask import Flask, jsonify
from flask_cors import CORS
from utils.config import load_config, get_cors_origins, reload_config

# Initialize Flask app
app = Flask(__name__)

# Force reload configuration (clears cache)
reload_config()

# Load configuration
config = load_config()

# Configure CORS
CORS(app, resources={
    r"/api/*": {
        "origins": get_cors_origins()
    }
})

# Import API routes
from api import routes
app.register_blueprint(routes.api, url_prefix='/api')


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "version": "1.0.0",
        "service": "Document Management Dashboard"
    })


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors."""
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    return jsonify({"error": "Internal server error"}), 500


if __name__ == '__main__':
    app.run(
        host=config['server']['host'],
        port=config['server']['port'],
        debug=config['server']['debug']
    )
