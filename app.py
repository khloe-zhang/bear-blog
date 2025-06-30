from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
import os

app = Flask(__name__)

# 使用环境变量 DATABASE_URI 让 Flask 连接 MySQL
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'DATABASE_URI', 
    'mysql+pymysql://flaskuser:yourpassword@mysql/flaskapp'  # 🚀 这里 `mysql` 是 `docker-compose` 里的 MySQL 容器名
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 创建数据库对象
db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True) # 主键
    name = db.Column(db.String(80), unique=True, nullable=False) # 姓名
    email = db.Column(db.String(120), unique=True, nullable=False) # 邮箱

with app.app_context():
    # 创建表
    db.create_all()

@app.route("/")
def home():
    return "Hello, AWS CI/CD updated on Feb 15! 🚀 Now with Auto Deployment! Now Flask is connected to MySQL! Now have Docker compose! Testing if security group works."

@app.route("/users", methods=["POST"])
def create_user(): # 通过 JSON 请求创建新用户
    data = request.get_json() # 这是在请求体中的 JSON 数据
    new_user = User(name=data["name"], email=data["email"])
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"message": "New user created!"}), 201

@app.route("/users", methods=["GET"])
def get_users(): # 获取所有用户
    users = User.query.all() 
    return jsonify([{"id": user.id, "name": user.name, "email": user.email} for user in users])
    # jsonify 的意思是将 Python 对象转换为 JSON 格式

@app.route("/users/<int:id>", methods=["GET"])
def get_user(id): # 通过 ID 获取用户
    user = User.query.get(id)
    if user:
        return jsonify({"id": user.id, "name": user.name, "email": user.email})
    return jsonify({"message": "User not found"}), 404

@app.route("/users/<int:id>", methods=["DELETE"])
def delete_user(id): # 通过 ID 删除用户
    user = User.query.get(id)
    if user:
        db.session.delete(user)
        db.session.commit()
        return jsonify({"message": "User deleted successfully!"})
    return jsonify({"message": "User not found"}), 404





if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)