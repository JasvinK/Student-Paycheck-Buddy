# Student Paycheck Budget Buddy 💰

A budgeting web application designed to help students manage their money between paychecks.

The app tracks income, expenses, budgets, and recurring bills, and provides a smart spending forecast so users know how much they can safely spend before their next payday.

This project was built as a portfolio project to practice **full-stack web development with Python and Flask**.

---

## Live Demo

The application is deployed online using **PythonAnywhere**.

Visit the live app here:

https://jasvink.pythonanywhere.com

If the database has not been initialized yet, visit:

https://jasvink.pythonanywhere.com/init

To explore the app with sample data, you can use **demo mode**:

https://jasvink.pythonanywhere.com/demo

---

## Features

- User authentication (sign up, login, logout)
- Track income and expenses
- Create budgets by category
- Track recurring bills
- Pay period tracking (bi-weekly pay schedule)
- Smart spending forecast
- Daily spending limit calculation
- Dashboard with financial insights
- Demo mode with sample data
- Clean responsive UI

---

## Tech Stack

### Backend
- Python
- Flask
- SQLite

### Frontend
- HTML
- CSS
- Jinja Templates

### Tools
- Git
- GitHub
- VS Code
- PythonAnywhere (deployment)

---
Deployment

This application is deployed using PythonAnywhere.

Deployment steps:
1. Push the project to GitHub
2. Clone the repository on PythonAnywhere
3. Create a virtual environment
4. Install dependencies with: pip install -r requirements.txt
5. Configure the WSGI file to load the Flask app: from app import create_app
                                                 application = create_app()
6. Reload the web app from the PythonAnywhere dashboard
   The live site is available at: https://jasvink.pythonanywhere.com
