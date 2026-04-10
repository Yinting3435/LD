from flask import Flask, render_template, request, redirect, url_for, jsonify
import os
from datetime import datetime
import cloudinary
import cloudinary.uploader
import cloudinary.api
from urllib.parse import urlparse
import os.path

app = Flask(__name__)

# 配置Cloudinary
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME', 'demo'),
    api_key=os.environ.get('CLOUDINARY_API_KEY', 'demo'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET', 'demo')
)

# 数据库连接函数 - 修复版
def get_db_connection():
    database_url = os.environ.get('DATABASE_URL')
    
    # 调试信息
    print(f"DATABASE_URL exists: {bool(database_url)}")
    if database_url:
        print(f"DATABASE_URL value: {database_url[:50]}...")
    
    # 在Vercel环境中，必须使用PostgreSQL
    # 只有在本地开发且明确设置了SQLite时才使用SQLite
    if database_url and database_url.startswith('postgres'):
        # 修复URL格式（某些服务返回postgres://，但psycopg2需要postgresql://）
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
        
        try:
            import psycopg2
            print("正在使用PostgreSQL连接...")
            conn = psycopg2.connect(
                database_url,
                sslmode='require'
            )
            return conn
        except Exception as e:
            print(f"PostgreSQL连接失败: {e}")
            raise Exception(f"无法连接到PostgreSQL数据库: {e}")
    
    # 只有在本地开发且没有DATABASE_URL时使用SQLite
    else:
        # 检查是否是Vercel环境
        if os.environ.get('VERCEL'):
            raise Exception("在Vercel环境中必须配置DATABASE_URL环境变量")
        
        # 本地开发使用SQLite
        import sqlite3
        print("本地开发：使用SQLite数据库")
        conn = sqlite3.connect('love_diary.db')
        return conn

# 初始化数据库
def init_db():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # 检查表是否存在
        c.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'diary'
            )
        """)
        table_exists = c.fetchone()[0]
        
        if not table_exists:
            # 创建表
            c.execute('''
                CREATE TABLE diary (
                    id SERIAL PRIMARY KEY,
                    content TEXT NOT NULL,
                    img_url TEXT,
                    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            print("✅ 数据库表已创建")
        else:
            print("✅ 数据库表已存在")
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"数据库初始化错误: {e}")
        # 不抛出异常，允许应用继续运行

# 计算恋爱天数
def calculate_love_days():
    start_date = datetime(2026, 4, 5)  # 恋爱开始日期
    today = datetime.now()
    # 清除时间部分，只比较日期
    start_date = datetime(start_date.year, start_date.month, start_date.day)
    today = datetime(today.year, today.month, today.day)
    
    # 计算天数差
    time_diff = today - start_date
    return max(0, time_diff.days)  # 确保不会显示负数

# 首页
@app.route('/', methods=['GET', 'POST'])
def index():
    # 计算恋爱天数
    love_days = calculate_love_days()
    
    # 保存日记
    if request.method == 'POST' and 'content' in request.form:
        content = request.form['content']
        img = request.files.get('img')
        img_url = None
        
        if img and img.filename:
            try:
                # 上传图片到Cloudinary
                upload_result = cloudinary.uploader.upload(img)
                img_url = upload_result.get('secure_url')
            except Exception as e:
                print(f"图片上传失败: {e}")
                img_url = None
        
        try:
            conn = get_db_connection()
            c = conn.cursor()
            
            # 插入数据
            c.execute('INSERT INTO diary (content, img_url) VALUES (%s, %s)', 
                     (content, img_url))
            
            conn.commit()
            conn.close()
            return redirect(url_for('index'))
        except Exception as e:
            return f"保存日记时出错: {e}", 500

    # 读取所有日记
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        c.execute('SELECT id, content, img_url, create_time FROM diary ORDER BY create_time DESC')
        diaries = c.fetchall()
        conn.close()
    except Exception as e:
        print(f"读取日记时出错: {e}")
        diaries = []

    return render_template('index.html', diaries=diaries, love_days=love_days)

# 删除日记的路由
@app.route('/delete/<int:diary_id>', methods=['POST'])
def delete_diary(diary_id):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # 首先获取日记信息，包括图片URL
        c.execute('SELECT img_url FROM diary WHERE id = %s', (diary_id,))
        result = c.fetchone()
        
        if result:
            img_url = result[0]
            # 如果有图片，从Cloudinary删除
            if img_url and 'cloudinary.com' in img_url:
                try:
                    # 从URL中提取public_id
                    public_id = img_url.split('/')[-1].split('.')[0]
                    cloudinary.uploader.destroy(public_id)
                except Exception as e:
                    print(f"删除Cloudinary图片失败: {e}")
            
            # 从数据库中删除日记
            c.execute('DELETE FROM diary WHERE id = %s', (diary_id,))
            conn.commit()
        
        conn.close()
        return jsonify({'success': True, 'message': '日记删除成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'}), 500

# API端点：获取恋爱天数
@app.route('/api/love_days')
def api_love_days():
    return jsonify({'love_days': calculate_love_days()})

# 健康检查
@app.route('/health')
def health():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT 1')
        result = c.fetchone()
        conn.close()
        return 'OK - 数据库连接正常'
    except Exception as e:
        return f'ERROR - 数据库连接失败: {e}', 500

# 环境检查路由
@app.route('/env-check')
def env_check():
    env_info = {
        'DATABASE_URL_exists': bool(os.environ.get('DATABASE_URL')),
        'CLOUDINARY_CLOUD_NAME_exists': bool(os.environ.get('CLOUDINARY_CLOUD_NAME')),
        'CLOUDINARY_API_KEY_exists': bool(os.environ.get('CLOUDINARY_API_KEY')),
        'CLOUDINARY_API_SECRET_exists': bool(os.environ.get('CLOUDINARY_API_SECRET')),
        'VERCEL_environment': bool(os.environ.get('VERCEL')),
    }
    
    # 安全地显示DATABASE_URL的一部分
    db_url = os.environ.get('DATABASE_URL', '')
    if db_url:
        env_info['DATABASE_URL_prefix'] = db_url[:20] + '...' if len(db_url) > 20 else db_url
    
    return jsonify(env_info)

if __name__ == '__main__':
    init_db()
    # 本地+手机都能访问
    app.run(host='0.0.0.0', port=8080, debug=True)
