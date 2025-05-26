    import logging
    import sqlite3
    import json
    import time
    import random
    import requests
    import asyncio
    from datetime import datetime
    from typing import Optional, Dict, List, Any
    from bs4 import BeautifulSoup
    from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
    from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup

    # Configure logging
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    logger = logging.getLogger(__name__)

    # Configuration
    BOT_TOKEN = "7590867244:AAFPcHwAr6Wktua1cQPDL-4uUamtsd8ea6U"
    BOT_NAME = "Docdot"
    OPENROUTER_API_KEY = "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"

    CATEGORIES = {
        "Anatomy": [
            "Head and Neck",
            "Upper Limb",
            "Thorax",
            "Lower Limb",
            "Pelvis and Perineum",
            "Neuroanatomy",
            "Abdomen"
        ],
        "Physiology": [
            "Cell",
            "Nerve and Muscle",
            "Blood",
            "Endocrine",
            "Reproductive",
            "Gastrointestinal Tract",
            "Renal",
            "Cardiovascular System",
            "Respiration",
            "Medical Genetics",
            "Neurophysiology"
        ]
    }

    def load_quiz_data() -> Dict[str, Any]:
        try:
            with open('image_data.json', 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading quiz data: {str(e)}")
            return {}

    def get_random_image(category):
        data = load_quiz_data()
        subcategories = list(data[category].keys())
        selected = random.choice(subcategories)
        return data[category][selected]

    # Database initialization
    def init_db():
        conn = sqlite3.connect('questions.db')
        cursor = conn.cursor()

        # Create questions table if it doesn't exist
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY,
            question TEXT NOT NULL,
            answer BOOLEAN NOT NULL,
            explanation TEXT,
            ai_explanation TEXT,
            reference_data TEXT,
            category TEXT NOT NULL
        )
        ''')

        # Create user_stats table if it doesn't exist
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_stats (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            total_attempts INTEGER DEFAULT 0,
            correct_answers INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0,
            max_streak INTEGER DEFAULT 0,
            last_quiz_date TEXT,
            category_stats TEXT
        )
        ''')

        conn.commit()
        conn.close()

    class QuizSession:
        def __init__(self):
            self.total_attempts = 0
            self.correct_answers = 0
            self.category_stats = {}
            self.streak = 0
            self.max_streak = 0
            self.last_quiz_date = None

        def record_answer(self, question, is_correct):
            self.total_attempts += 1
            category = question['category']

            if category not in self.category_stats:
                self.category_stats[category] = {'attempts': 0, 'correct': 0}

            self.category_stats[category]['attempts'] += 1

            if is_correct:
                self.correct_answers += 1
                self.category_stats[category]['correct'] += 1
                self.streak += 1
                self.max_streak = max(self.streak, self.max_streak)
            else:
                self.streak = 0

            self.last_quiz_date = time.strftime("%Y-%m-%d")

        def get_accuracy(self):
            if self.total_attempts == 0:
                return 0
            return (self.correct_answers / self.total_attempts) * 100

        def get_category_accuracy(self, category):
            if category not in self.category_stats:
                return 0
            stats = self.category_stats[category]
            if stats['attempts'] == 0:
                return 0
            return (stats['correct'] / stats['attempts']) * 100

        def get_achievements(self):
            achievements = []
            if self.total_attempts >= 50:
                achievements.append("🏆 Quiz Master (50+ questions)")
            if self.max_streak >= 5:
                achievements.append("🔥 Hot Streak (5+ correct)")
            if self.get_accuracy() >= 80 and self.total_attempts >= 20:
                achievements.append("🎯 Expert (80%+ accuracy)")
            return achievements

    def save_user_stats(user_id, username, first_name, quiz_session):
        conn = sqlite3.connect('questions.db')
        cursor = conn.cursor()

        cursor.execute('''
        INSERT OR REPLACE INTO user_stats
        (user_id, username, first_name, total_attempts, correct_answers, streak, max_streak, last_quiz_date, category_stats)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            username,
            first_name,
            quiz_session.total_attempts,
            quiz_session.correct_answers,
            quiz_session.streak,
            quiz_session.max_streak,
            quiz_session.last_quiz_date,
            json.dumps(quiz_session.category_stats)
        ))

        conn.commit()
        conn.close()

    def load_user_stats(user_id):
        try:
            conn = sqlite3.connect('questions.db')
            cursor = conn.cursor()

            # First check if the table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_stats'")
            if not cursor.fetchone():
                # Table doesn't exist, create it
                init_db()
                return QuizSession()

            cursor.execute('SELECT * FROM user_stats WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            conn.close()

            if result:
                quiz_session = QuizSession()
                quiz_session.total_attempts = result[3]
                quiz_session.correct_answers = result[4]
                quiz_session.streak = result[5]
                quiz_session.max_streak = result[6]
                quiz_session.last_quiz_date = result[7]
                quiz_session.category_stats = json.loads(result[8]) if result[8] else {}
                return quiz_session

            return QuizSession()
        except Exception as e:
            logger.error(f"Error loading user stats: {str(e)}")
            return QuizSession()

    def get_random_question(category=None):
        conn = sqlite3.connect('questions.db')
        cursor = conn.cursor()

        # Log the request for debugging
        logger.info(f"Getting question for category: {category}")

        if category and category != "All Categories":
            # Make sure we're getting questions ONLY from the exact category requested
            # This ensures Thorax questions only come from Thorax category
            cursor.execute('SELECT * FROM questions WHERE category = ? ORDER BY RANDOM() LIMIT 1', (category,))
            # Log how many questions are available in this category
            cursor.execute('SELECT COUNT(*) FROM questions WHERE category = ?', (category,))
            count = cursor.fetchone()[0]
            logger.info(f"Found {count} questions in category: {category}")
        else:
            # For "All Categories", get a truly random question from any category
            cursor.execute('SELECT * FROM questions ORDER BY RANDOM() LIMIT 1')
            # Log total questions available
            cursor.execute('SELECT COUNT(*) FROM questions')
            count = cursor.fetchone()[0]
            logger.info(f"Found {count} total questions across all categories")

        # Get the random question
        if category and category != "All Categories":
            cursor.execute('SELECT * FROM questions WHERE category = ? ORDER BY RANDOM() LIMIT 1', (category,))
        else:
            cursor.execute('SELECT * FROM questions ORDER BY RANDOM() LIMIT 1')
        question = cursor.fetchone()
        conn.close()

        if question:
            return {
                'id': question[0],
                'question': question[1],
                'answer': bool(question[2]),
                'explanation': question[3],
                'ai_explanation': question[4],
                'references': json.loads(question[5] if question[5] else "{}"),
                'category': question[6]
            }
        return None

    def get_category_leaderboard(category=None):
        """Get the leaderboard data for a specific category or overall."""
        try:
            conn = sqlite3.connect('questions.db')
            cursor = conn.cursor()

            # First check if the table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_stats'")
            if not cursor.fetchone():
                # Table doesn't exist, create it
                init_db()
                return []

            cursor.execute('SELECT user_id, username, first_name, category_stats FROM user_stats')
            users = cursor.fetchall()
            conn.close()

            leaderboard = []

            for user in users:
                user_id, username, first_name, category_stats_json = user
                display_name = username if username else first_name

                if category_stats_json:
                    category_stats = json.loads(category_stats_json)

                    if category:
                        # For specific category
                        if category in category_stats:
                            stats = category_stats[category]
                            if stats['attempts'] > 0:
                                accuracy = (stats['correct'] / stats['attempts']) * 100
                                leaderboard.append({
                                    'user_id': user_id,
                                    'name': display_name,
                                    'accuracy': accuracy,
                                    'attempts': stats['attempts'],
                                    'correct': stats['correct']
                                })
                    else:
                        # For overall score
                        total_attempts = 0
                        total_correct = 0

                        for cat, stats in category_stats.items():
                            total_attempts += stats['attempts']
                            total_correct += stats['correct']

                        if total_attempts > 0:
                            accuracy = (total_correct / total_attempts) * 100
                            leaderboard.append({
                                'user_id': user_id,
                                'name': display_name,
                                'accuracy': accuracy,
                                'attempts': total_attempts,
                                'correct': total_correct
                            })

            # Sort by accuracy (highest first)
            leaderboard.sort(key=lambda x: x['accuracy'], reverse=True)
            return leaderboard
        except Exception as e:
            logger.error(f"Error getting leaderboard: {str(e)}")
            return []


    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user

        # Load user stats
        user_id = user.id
        quiz_session = load_user_stats(user_id)
        context.user_data['quiz_session'] = quiz_session

        welcome_message = (
            f"🩺 *Hi, {user.first_name}! Welcome to {BOT_NAME}* 🩺\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "Your interactive medical learning companion!\n\n"
            "🎯 *KEY FEATURES*\n"
            "📚 Comprehensive Anatomy & Physiology Quizzes\n"
            "📊 Performance Tracking\n"
            "🧠 AI-Powered Explanations\n"
            "💭 Ask Medical Questions\n\n"
            "⚡️ *QUICK COMMANDS*\n"
            "📋 /stats - Your Performance\n"
            "🗂 /categories - Browse Topics\n"
            "❓ /help - Get Assistance\n"
            "💬 /ask - Ask Medical Questions\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "*Ready to test your medical knowledge?*"
        )

        keyboard = [
            [
                InlineKeyboardButton("🎯 Start Quiz", callback_data="main_categories"),
                InlineKeyboardButton("🏆 Top Scores", callback_data="leaderboard")
            ],
            [
                InlineKeyboardButton("📊 My Progress", callback_data="show_stats"),
                InlineKeyboardButton("🔬 Image Quiz", callback_data="image_quiz")
            ],
            [
                InlineKeyboardButton("🧠 Ask AI Tutor", callback_data="ask_help"),
                InlineKeyboardButton("💝 Donate", callback_data="donations")
            ],
            [
                InlineKeyboardButton("👥 Join Community", url="https://chat.whatsapp.com/I1pKGskAUOf5HPhfjfH58q"),
                InlineKeyboardButton("ℹ️ About Bot", callback_data="about")
            ]
        ]

        await update.message.reply_text(
            welcome_message,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def show_main_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        keyboard = [
            [InlineKeyboardButton("🦴 Anatomy", callback_data="category_Anatomy")],
            [InlineKeyboardButton("🧬 Physiology", callback_data="category_Physiology")],
            [InlineKeyboardButton("🔄 All Categories", callback_data="category_all")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
        ]

        await query.edit_message_text(
            "*Select a Main Category:*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def show_subcategories(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        main_category = query.data.replace("category_", "")

        if main_category == "all":
            await quiz(update, context, category="All Categories")
            return

        subcategories = CATEGORIES.get(main_category, [])

        keyboard = []
        row = []
        for i, subcat in enumerate(subcategories):
            row.append(InlineKeyboardButton(subcat, callback_data=f"subcategory_{subcat}"))
            if (i + 1) % 2 == 0 or i == len(subcategories) - 1:
                keyboard.append(row)
                row = []

        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="main_categories")])

        await query.edit_message_text(
            f"*{main_category} Subcategories:*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE, category=None):
        query = update.callback_query

        if not category:
            category = query.data.replace("subcategory_", "")

        # Log the requested category for debugging
        logger.info(f"Quiz requested for category: {category}")

        # Store the current category in user_data to ensure next questions stay in the same category
        context.user_data['current_category'] = category

        if category == "All Categories":
            category = None

        question = get_random_question(category)
        if not question:
            await query.edit_message_text(
                "No questions available for this category.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back", callback_data="main_categories")
                ]])
            )
            return

        context.user_data['current_question'] = question

        message_text = (
            f"📋 *{question['category'].upper()} QUESTION*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{question['question']}\n\n"
            "📍 Select an answer below:\n"
            "*True or False*"
        )

        keyboard = [
            [InlineKeyboardButton("True", callback_data="answer_true"),
             InlineKeyboardButton("False", callback_data="answer_false")],
            [InlineKeyboardButton("🔄 Skip", callback_data=f"subcategory_{category}" if category else "subcategory_All Categories")],
            [InlineKeyboardButton("❌ End Quiz", callback_data="main_categories")]
        ]

        await query.edit_message_text(
            message_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def check_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        user = update.effective_user
        user_answer = query.data == "answer_true"
        current_question = context.user_data.get('current_question')

        if not current_question:
            await query.edit_message_text("Session expired. Please start a new quiz.")
            return

        is_correct = user_answer == current_question['answer']
        quiz_session = context.user_data.get('quiz_session', QuizSession())
        quiz_session.record_answer(current_question, is_correct)
        context.user_data['quiz_session'] = quiz_session

        # Save user stats
        save_user_stats(user.id, user.username, user.first_name, quiz_session)

        response = (
            f"{'✅ Correct!' if is_correct else '❌ Incorrect!'}\n\n"
            f"*Question:*\n{current_question['question']}\n\n"
            f"*Explanation:*\n{current_question['explanation']}\n\n"
        )

        if current_question.get('ai_explanation'):
            response += f"*Detailed Explanation:*\n{current_question['ai_explanation']}\n\n"

        if current_question.get('references'):
            response += "*References:*\n"
            for book, page in current_question['references'].items():
                response += f"📚 {book}: {page}\n"

        # Use the stored category to ensure we stay in the same category for the next question
        current_category = context.user_data.get('current_category', current_question['category'])
        logger.info(f"Using category for next question: {current_category}")

        keyboard = [
            [InlineKeyboardButton("Next Question ▶️", callback_data=f"subcategory_{current_category}")],
            [InlineKeyboardButton("🔙 Categories", callback_data="main_categories")]
        ]

        await query.edit_message_text(
            response,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user

        # Load user stats
        quiz_session = context.user_data.get('quiz_session')
        if not quiz_session:
            quiz_session = load_user_stats(user.id)
            context.user_data['quiz_session'] = quiz_session

        accuracy = quiz_session.get_accuracy()
        performance_emoji = "🎯" if accuracy >= 80 else "📈" if accuracy >= 60 else "📊"

        stats_message = (
            f"📚 *{user.first_name}'s Medical Knowledge Journey* 📚\n"
            "═══════════════════════\n\n"
            f"{performance_emoji} *Overall Performance*\n"
            f"• Questions Attempted: {quiz_session.total_attempts}\n"
            f"• Correct Answers: {quiz_session.correct_answers}\n"
            f"• Overall Accuracy: {accuracy:.1f}%\n"
            f"• Current Streak: {quiz_session.streak} 🔥\n"
            f"• Best Streak: {quiz_session.max_streak} ⭐\n\n"
            "*📊 Category Breakdown*\n"
        )

        for category, stats in quiz_session.category_stats.items():
            cat_accuracy = quiz_session.get_category_accuracy(category)
            progress_bar = "▰" * int(cat_accuracy/10) + "▱" * (10 - int(cat_accuracy/10))
            stats_message += f"\n{category}:\n{progress_bar} {cat_accuracy:.1f}%\n"

        achievements = quiz_session.get_achievements()
        if achievements:
            stats_message += "\n*🏆 Achievements*\n" + "\n".join(achievements)

        progress_bar = "█" * int(accuracy/10) + "▒" * (10 - int(accuracy/10))
        if accuracy >= 80:
            stats_message += f"\n\n📊 Progress: [{progress_bar}] {accuracy:.1f}%\n"
            stats_message += "🌟 Outstanding performance! Keep shining!"
        elif accuracy >= 60:
            stats_message += "\n\n💪 Great progress! Keep pushing!"
        else:
            stats_message += "\n\n📚 Keep learning! You're on the right path!"

        keyboard = [
            [InlineKeyboardButton("📚 Continue Learning", callback_data="main_categories")],
            [InlineKeyboardButton("📊 Detailed Analysis", callback_data="detailed_stats")]
        ]

        if update.callback_query:
            await update.callback_query.edit_message_text(
                stats_message,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.message.reply_text(
                stats_message,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Display the leaderboard for all categories or a specific category."""
        query = update.callback_query
        await query.answer()

        category = context.user_data.get('leaderboard_category', None)

        if query.data.startswith("leaderboard_"):
            category = query.data.replace("leaderboard_", "")
            context.user_data['leaderboard_category'] = category

        # Get leaderboard data
        if category == "overall":
            category = None  # For overall stats
            title = "Overall Leaderboard"
        else:
            title = f"{category} Leaderboard"

        leaderboard = get_category_leaderboard(category)

        if not leaderboard:
            message = f"*{title}*\n\nNo data available for this category yet."
        else:
            message = f"*{title}*\n\n"
            # Show only top performer for each category with clear highest score format
            if len(leaderboard) > 0:
                top_user = leaderboard[0]  # Get the top performer
                message += f"🏆 *{top_user['name']}* Highest Score - {top_user['accuracy']:.1f}%\n"
                message += f"Questions attempted: {top_user['attempts']}\n"
                message += f"Correct answers: {top_user['correct']}\n\n"

            # Add the rest of the leaderboard (up to 9 more entries)
            for i, entry in enumerate(leaderboard[1:10], 2):  # Start from 2nd place
                if i == 2:
                    medal = "🥈"
                elif i == 3:
                    medal = "🥉"
                else:
                    medal = f"{i}."

                message += f"{medal} *{entry['name']}*: {entry['accuracy']:.1f}%\n"

        # Create category selection keyboard
        keyboard = []

        # Add "Overall" button
        keyboard.append([InlineKeyboardButton("📊 Overall", callback_data="leaderboard_overall")])

        # Add buttons for main categories
        main_categories = []
        for main_category in CATEGORIES:
            main_categories.append(InlineKeyboardButton(f"{main_category}", callback_data=f"leaderboard_main_{main_category}"))

        # Split main categories into rows of 2
        for i in range(0, len(main_categories), 2):
            row = main_categories[i:i+2]
            keyboard.append(row)

        # Add subcategory buttons if a main category is selected
        if query.data.startswith("leaderboard_main_"):
            main_category = query.data.replace("leaderboard_main_", "")
            subcategories = CATEGORIES.get(main_category, [])

            subcat_buttons = []
            for subcat in subcategories:
                subcat_buttons.append(InlineKeyboardButton(subcat, callback_data=f"leaderboard_{subcat}"))

            # Split subcategories into rows of 2
            for i in range(0, len(subcat_buttons), 2):
                row = subcat_buttons[i:i+2]
                keyboard.append(row)

        # Add back button
        keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")])

        await query.edit_message_text(
            message,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def study_guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        message = (
            "*📚 STUDY GUIDE*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Here are some resources to help your medical studies:\n\n"
            "*Recommended Resources:*\n"
            "• Gray's Anatomy for Students\n"
            "• Guyton and Hall Textbook of Medical Physiology\n"
            "• Netter's Atlas of Human Anatomy\n"
            "• BRS Physiology\n\n"
            "*Study Tips:*\n"
            "• Use active recall and spaced repetition\n"
            "• Create mind maps for complex topics\n"
            "• Join study groups for discussion\n"
            "• Use mnemonics for difficult lists\n\n"
            "*Online Resources:*\n"
            "• Osmosis.org\n"
            "• Kenhub.com\n"
            "• TeachMeAnatomy.info"
        )

        keyboard = [
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
        ]

        await query.edit_message_text(
            message,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def ask_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        message = (
            "*🧠 ASK AI MEDICAL TUTOR*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Need help with a medical concept? Ask me anything about anatomy or physiology!\n\n"
            "Simply type your question after using the /ask command.\n\n"
            "*Example:*\n"
            "/ask What are the layers of the heart wall?\n\n"
            "I'll do my best to provide you with a detailed explanation."
        )

        keyboard = [
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
        ]

        await query.edit_message_text(
            message,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def donations(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        message = (
            "*💝 SUPPORT OUR DEVELOPMENT*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Your support helps us improve and expand our educational resources!\n\n"
            "*Why Donate?*\n"
            "• Help us develop more features\n"
            "• Support content creation\n"
            "• Enable AI improvements\n"
            "• Keep the service running\n\n"
            "*Donation Methods:*\n"
            "━━━━━━━━━━━━━━━\n"
            "*EcoCash Payment*\n"
            "Number: +263 78 483 7096\n"
            "Name: Takudzwa Zimbwa\n\n"
            "*How to Donate:*\n"
            "1. Open your EcoCash Menu\n"
            "2. Select 'Send Money'\n"
            "3. Enter: 0784837096\n"
            "4. Enter desired amount\n"
            "5. Confirm payment\n\n"
            "💌 *Every contribution matters!*\n"
            "Thank you for supporting medical education."
        )

        keyboard = [
            [InlineKeyboardButton("✅ I've Made a Donation", callback_data="donation_complete")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
        ]

        await query.edit_message_text(
            message,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def donation_complete(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        message = (
            "*🎉 Thank You for Your Support!*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Your contribution will help us:\n"
            "• Create more educational content\n"
            "• Improve our AI capabilities\n"
            "• Develop new features\n\n"
            "We truly appreciate your support in making medical education more accessible!\n\n"
            "Continue exploring and learning with us! 📚"
        )

        keyboard = [
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
        ]

        await query.edit_message_text(
            message,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        message = (
            f"*ℹ️ ABOUT {BOT_NAME}*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{BOT_NAME} is your personal medical education assistant, designed to help medical students master anatomy and physiology through interactive quizzes and AI-powered explanations.\n\n"
            "*Features:*\n"
            "• True/False quiz questions with detailed explanations\n"
            "• Comprehensive coverage of medical topics\n"
            "• Performance tracking and statistics\n"
            "• AI-powered tutoring for complex concepts\n\n"
            "*Credits:*\n"
            "Developed by Ngonidzashe Zimbwa, with ❤️ for medical students worldwide\n\n"
            "*Version:* 1.0"
        )

        keyboard = [
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
        ]

        await query.edit_message_text(
            message,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def detailed_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        user = update.effective_user
        quiz_session = context.user_data.get('quiz_session')
        if not quiz_session:
            quiz_session = load_user_stats(user.id)
            context.user_data['quiz_session'] = quiz_session

        message = (
            f"*📊 {user.first_name}'s Detailed Statistics*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        # Overall stats
        accuracy = quiz_session.get_accuracy()
        message += f"*Overall Accuracy:* {accuracy:.1f}%\n"
        message += f"*Total Questions:* {quiz_session.total_attempts}\n"
        message += f"*Correct Answers:* {quiz_session.correct_answers}\n"
        message += f"*Current Streak:* {quiz_session.streak}\n"
        message += f"*Best Streak:* {quiz_session.max_streak}\n\n"

        # Category breakdown
        message += "*Category Performance:*\n\n"

        for main_category in CATEGORIES:
            message += f"*{main_category}*\n"

            for subcategory in CATEGORIES[main_category]:
                if subcategory in quiz_session.category_stats:
                    stats = quiz_session.category_stats[subcategory]
                    if stats['attempts'] > 0:
                        cat_accuracy = (stats['correct'] / stats['attempts']) * 100
                        message += f"• {subcategory}: {cat_accuracy:.1f}% ({stats['correct']}/{stats['attempts']})\n"
                else:
                    message += f"• {subcategory}: No attempts yet\n"

            message += "\n"

        keyboard = [
            [InlineKeyboardButton("🔙 Back", callback_data="show_stats")],
            [InlineKeyboardButton("📚 Continue Learning", callback_data="main_categories")]
        ]

        await query.edit_message_text(
            message,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def start_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Return to start menu."""
        query = update.callback_query

        if query:
            await query.answer()
            user = update.effective_user

            welcome_message = (
                f"🩺 *Hi, {user.first_name}! Welcome to {BOT_NAME}* 🩺\n\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "Your interactive medical learning companion!\n\n"
                "🎯*KEY FEATURES*\n"
                "📚 Comprehensive Anatomy & Physiology Quizzes\n"
                "📊 Performance Tracking\n"
                "🧠 AI-Powered Explanations\n"
                "💭 Ask Medical Questions\n\n"
                "⚡️ *QUICK COMMANDS*\n"
                "📋 /stats - Your Performance\n"
                "🗂 /categories - Browse Topics\n"
                "❓ /help - Get Assistance\n""💬 /ask - Ask Medical Questions\n\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "*Ready to test your medical knowledge?*"
            )

            keyboard = [
                [
                    InlineKeyboardButton("🎯 Start Quiz", callback_data="main_categories"),
                    InlineKeyboardButton("🏆 Top Scores", callback_data="leaderboard")
                ],
                [
                    InlineKeyboardButton("📊 My Progress", callback_data="show_stats"),
                    InlineKeyboardButton("🔬 Image Quiz ✨NEW", callback_data="image_quiz")
                ],
                [
                    InlineKeyboardButton("🧠 Ask AI Tutor", callback_data="ask_help"),
                    InlineKeyboardButton("💝 Donate", callback_data="donations")
                ],
                [
                    InlineKeyboardButton("👥 Join Community", url="https://chat.whatsapp.com/I1pKGskAUOf5HPhfjfH58q"),
                    InlineKeyboardButton("ℹ️ About Bot", callback_data="about")

    ]
            ]

            await query.edit_message_text(
                welcome_message,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    async def categories_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show categories via command."""
        keyboard = [
            [InlineKeyboardButton("🦴 Anatomy", callback_data="category_Anatomy")],
            [InlineKeyboardButton("🧬 Physiology", callback_data="category_Physiology")],
            [InlineKeyboardButton("🔄 All Categories", callback_data="category_all")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
        ]

        await update.message.reply_text(
            "*Select a Category to Start Quizzes:*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show stats via command."""
        await show_stats(update, context)

    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show help information."""
        help_text = (
            "*🩺 HELP GUIDE*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "*Available Commands:*\n"
            "/start - Start the bot and see main menu\n"
            "/categories - Browse quiz categories\n"
            "/stats - View your performance statistics\n"
            "/help - Show this help message\n"
            "/ask - Ask a medical question\n\n"
            "*How to Use:*\n"
            "1. Select a category from the main menu\n"
            "2. Choose a subcategory or take a random quiz\n"
            "3. Answer True/False questions\n"
            "4. Review explanations to enhance your learning\n\n"
            "*Got Questions?*\n"
            "Use /ask followed by your medical question to get AI-powered help."
        )

        keyboard = [
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
        ]

        await update.message.reply_text(
            help_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process user questions."""
        if not context.args:
            await update.message.reply_text(
                "*How to Ask Questions:*\n\n"
                "Use /ask followed by your medical question.\n\n"
                "*Example:*\n"
                "/ask What are the branches of the facial nerve?",
                parse_mode="Markdown"
            )
            return

        question = " ".join(context.args)

        # Let user know we're processing
        processing_message = await update.message.reply_text(
            "🧠 *Processing your question...*\n"
            "I'm thinking about this medical concept.",
            parse_mode="Markdown"
        )

        try:
            # Call the OpenRouter API
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "anthropic/claude-3-opus:beta",
                    "messages": [
                        {"role": "system", "content": "You are a helpful medical tutor specializing in anatomy and physiology."},
                        {"role": "user", "content": question}
                    ]
                }
            )

            data = response.json()

            if "choices" in data and len(data["choices"]) > 0:
                answer = data["choices"][0]["message"]["content"]

                # Send answer in chunks if needed (Telegram has message length limits)
                if len(answer) > 4000:
                    chunks = [answer[i:i+4000] for i in range(0, len(answer), 4000)]
                    await processing_message.delete()

                    for i, chunk in enumerate(chunks):
                        if i == 0:
                            await update.message.reply_text(
                                f"*Answer to: {question}*\n\n{chunk}",
                                parse_mode="Markdown"
                            )
                        else:
                            await update.message.reply_text(
                                chunk,
                                parse_mode="Markdown"
                            )
                else:
                    await processing_message.edit_text(
                        f"*Answer to: {question}*\n\n{answer}",
                        parse_mode="Markdown"
                    )


            else:
                await processing_message.edit_text(
                    "I couldn't process your question. Please try again.",
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Error in ask_command: {str(e)}")
            await processing_message.edit_text(
                "Sorry, I encountered an error while processing your question. Please try again later.",
                parse_mode="Markdown"
            )

    async def image_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        # Initialize or get user's image quiz stats
        if 'image_quiz_stats' not in context.user_data:
            context.user_data['image_quiz_stats'] = {
                'cadaver': {'attempts': 0, 'correct': 0},
                'histology': {'attempts': 0, 'correct': 0}
            }

        stats = context.user_data['image_quiz_stats']
        cadaver_accuracy = (stats['cadaver']['correct'] / stats['cadaver']['attempts'] * 100) if stats['cadaver']['attempts'] > 0 else 0
        histology_accuracy = (stats['histology']['correct'] / stats['histology']['attempts'] * 100) if stats['histology']['attempts'] > 0 else 0

        message = (
            "*🔬 INTERACTIVE IMAGE QUIZ*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Test your visual recognition skills!\n\n"
            "*Your Performance:*\n"
            f"🫀 Cadaver Quiz: {cadaver_accuracy:.1f}% ({stats['cadaver']['correct']}/{stats['cadaver']['attempts']})\n"
            f"🔬 Histology: {histology_accuracy:.1f}% ({stats['histology']['correct']}/{stats['histology']['attempts']})\n\n"
            "Select a category to begin:"
        )

        keyboard = [
            [InlineKeyboardButton("🫀 Anatomy Cadaver Quiz", callback_data="cadaver_quiz")],
            [InlineKeyboardButton("🔬 Histology Slides Quiz", callback_data="histology_quiz")],
            [InlineKeyboardButton("📊 View Stats", callback_data="image_quiz_stats")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
        ]

        await query.edit_message_text(
            message,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def get_hint(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        current_image = context.user_data.get('current_image')
        if not current_image:
            return

        if 'hints_used' not in context.user_data:
            context.user_data['hints_used'] = 0

        context.user_data['hints_used'] += 1
        hints_used = context.user_data['hints_used']

        # Get a random label as a hint
        labels = current_image['labels']
        hint = random.choice(labels)

        await query.answer(f"Hint {hints_used}: {hint}", show_alert=True)

    async def show_image_quiz_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        stats = context.user_data.get('image_quiz_stats', {
            'cadaver': {'attempts': 0, 'correct': 0},
            'histology': {'attempts': 0, 'correct': 0}
        })

        completed_images = len(context.user_data.get('completed_images', set()))
        total_images = len(load_quiz_data()['cadaver']) + len(load_quiz_data()['histology'])

        message = (
            "*📊 IMAGE QUIZ STATISTICS*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"*Overall Progress:* {(completed_images/total_images)*100:.1f}%\n"
            f"*Images Completed:* {completed_images}/{total_images}\n\n"
            "*Category Performance:*\n"
            f"🫀 *Cadaver Quiz*\n"
            f"• Accuracy: {(stats['cadaver']['correct']/stats['cadaver']['attempts']*100 if stats['cadaver']['attempts']>0 else 0):.1f}%\n"
            f"• Correct: {stats['cadaver']['correct']}/{stats['cadaver']['attempts']}\n\n"
            f"🔬 *Histology Quiz*\n"
            f"• Accuracy: {(stats['histology']['correct']/stats['histology']['attempts']*100 if stats['histology']['attempts']>0 else 0):.1f}%\n"
            f"• Correct: {stats['histology']['correct']}/{stats['histology']['attempts']}\n\n"
            "*Keep practicing to improve your scores!*"
        )

        keyboard = [
            [InlineKeyboardButton("🔄 Return to Quiz", callback_data="image_quiz")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="start_menu")]
        ]

        await query.edit_message_text(
            message,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )



    async def handle_cadaver_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        # Load image data and select random image
        with open('image_data.json', 'r') as f:
            all_images = json.load(f)

        cadaver_images = all_images.get('cadaver', {})
        if not cadaver_images:
            await query.edit_message_text("No cadaver images available.")
            return

        # Select random image
        image_key = random.choice(list(cadaver_images.keys()))
        image_data = cadaver_images[image_key]
        context.user_data['current_image'] = image_data
        context.user_data['current_quiz_type'] = 'cadaver'
        context.user_data['hints_used'] = 0
        context.user_data['awaiting_answers'] = True
        context.user_data['student_answers'] = []

        # Track progress
        if 'completed_images' not in context.user_data:
            context.user_data['completed_images'] = set()
        total_images = len(cadaver_images)
        completed = len(context.user_data['completed_images'])

        message = (
            "*🫀 ANATOMY CADAVER QUIZ*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Label the marked structures in this image:\n\n"
            "Type your answers one by one. Each answer should be on a new line.\n"
            f"Number of structures to identify: {len(image_data['labels'])}\n\n"
            "Example format:\n"
            "1. Your first answer\n"
            "2. Your second answer\n"
            "etc."
        )

        keyboard = [
            [InlineKeyboardButton("Submit Answers", callback_data="submit_answers")],
            [InlineKeyboardButton("Get Hint", callback_data="get_hint")],
            [InlineKeyboardButton("Next Image", callback_data="cadaver_quiz")],
            [InlineKeyboardButton("🔙 Back", callback_data="image_quiz")]
        ]

        try:
            # Delete previous message if it exists
            if query.message.photo:
                await query.message.delete()

            # Send new image
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=open(image_data['path'], 'rb'),
                caption=message,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Error sending image: {str(e)}")
            await query.edit_message_text(
                "Error loading image. Please try again.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="image_quiz")]])
            )

    async def handle_histology_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        # Load image data and select random image
        with open('image_data.json', 'r') as f:
            all_images = json.load(f)

        histology_images = all_images.get('histology', {})
        if not histology_images:
            await query.edit_message_text("No histology images available.")
            return

        # Select random image
        image_key = random.choice(list(histology_images.keys()))
        image_data = histology_images[image_key]
        context.user_data['current_image'] = image_data
        context.user_data['current_quiz_type'] = 'histology'
        context.user_data['hints_used'] = 0
        context.user_data['awaiting_answers'] = True
        context.user_data['student_answers'] = []

        # Track progress
        if 'completed_images' not in context.user_data:
            context.user_data['completed_images'] = set()
        total_images = len(histology_images)
        completed = len(context.user_data['completed_images'])

        message = (
            "*🔬 HISTOLOGY SLIDE QUIZ*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Label the marked structures in this histological slide:\n\n"
            "Type your answers one by one. Each answer should be on a new line.\n"
            f"Number of structures to identify: {len(image_data['labels'])}\n\n"
            "Example format:\n"
            "1. Your first answer\n"
            "2. Your second answer\n"
            "etc."
        )

        keyboard = [
            [InlineKeyboardButton("Submit Answers", callback_data="submit_answers")],
            [InlineKeyboardButton("Get Hint", callback_data="get_hint")],
            [InlineKeyboardButton("Next Slide", callback_data="histology_quiz")],
            [InlineKeyboardButton("🔙 Back", callback_data="image_quiz")]
        ]

        try:
            # Delete previous message if it exists
            if query.message.photo:
                await query.message.delete()

            # Send new image
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=open(image_data['path'], 'rb'),
                caption=message,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Error sending image: {str(e)}")
            await query.edit_message_text(
                "Error loading image. Please try again.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="image_quiz")]])
            )

    async def show_labels(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        current_image = context.user_data.get('current_image')
        if not current_image:
            await query.edit_message_text("Session expired. Please start a new quiz.")
            return

        labels = current_image['labels']
        labels_text = "\n".join([f"• {label}" for label in labels])

        message = (
            "*🏷️ CORRECT LABELS*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{labels_text}\n\n"
            "Select an option below:"
        )

        quiz_type = "cadaver_quiz" if "cadaver" in current_image['path'] else "histology_quiz"

        keyboard = [
            [InlineKeyboardButton("Next Image", callback_data=quiz_type)],
            [InlineKeyboardButton("🔙 Back to Categories", callback_data="image_quiz")]
        ]

        # For histology, send new message instead of editing
        if quiz_type == "histology_quiz":
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=message,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query.edit_message_text(
                message,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    async def submit_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        current_image = context.user_data.get('current_image')
        quiz_type = context.user_data.get('current_quiz_type')
        student_answers = context.user_data.get('student_answers', [])
        hints_used = context.user_data.get('hints_used', 0)

        if not current_image or not quiz_type:
            await query.edit_message_text("Session expired. Please start a new quiz.")
            return

        # Calculate score and get feedback
        score, feedback = await validate_answers(student_answers, current_image['labels'])

        # Apply hint penalty
        hint_penalty = hints_used * 5  # 5% penalty per hint
        final_score = max(score - hint_penalty, 0)

        # Update stats
        if 'image_quiz_stats' not in context.user_data:
            context.user_data['image_quiz_stats'] = {
                'cadaver': {'attempts': 0, 'correct': 0},
                'histology': {'attempts': 0, 'correct': 0}
            }

        context.user_data['image_quiz_stats'][quiz_type]['attempts'] += 1
        if final_score >= 70:  # Consider it correct if score is 70% or higher
            context.user_data['image_quiz_stats'][quiz_type]['correct'] += 1

        # Track completed images
        if 'completed_images' not in context.user_data:
            context.user_data['completed_images'] = set()
        context.user_data['completed_images'].add(current_image['path'])

        feedback_text = "\n".join(feedback)

        # Get correct labels
        correct_labels = current_image['labels']
        labels_text = "\n".join([f"• {label}" for label in correct_labels])

        message = (
            "*🏆 QUIZ RESULTS*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"*Final Score:* {final_score:.1f}%\n"
            f"*Raw Score:* {score:.1f}%\n"
            f"*Hint Penalty:* -{hint_penalty}%\n"
            f"*Hints Used:* {hints_used}\n\n"
            "*Feedback:*\n"
            f"{feedback_text}\n\n"
            "*Correct Labels:*\n"
            f"{labels_text}\n\n"
            f"{'🌟 Excellent work!' if final_score >= 80 else '💪 Keep practicing!'}"
        )

        quiz_type = context.user_data.get('current_quiz_type')
        next_quiz = "histology_quiz" if quiz_type == "histology" else "cadaver_quiz"
        keyboard = [
            [InlineKeyboardButton("Next Image", callback_data=next_quiz),
             InlineKeyboardButton("🔙 Back to Menu", callback_data="image_quiz")]
        ]

        # Send the labels as a response message
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=message,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def collect_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Collect and process student answers for image quizzes."""
        if not context.user_data.get('awaiting_answers'):
            return

        message_text = update.message.text
        answers = [ans.strip() for ans in message_text.split('\n') if ans.strip()]

        current_image = context.user_data.get('current_image')
        if not current_image:
            await update.message.reply_text("Session expired. Please start a new quiz.")
            return

        context.user_data['student_answers'] = answers
        await update.message.reply_text(
            f"✅ Received {len(answers)} answers.\nClick 'Submit Answers' to check your responses.",
            parse_mode="Markdown"
        )

    async def validate_answers(student_answers, correct_labels):
        """Compare student answers with correct labels and calculate score."""
        if not student_answers:
            return 0, []

        correct_count = 0
        feedback = []

        # Normalize answers for comparison
        normalized_correct = [label.lower().split('.')[-1].strip() for label in correct_labels]
        normalized_student = [ans.lower().split('.')[-1].strip() for ans in student_answers]

        for i, (student, correct) in enumerate(zip(normalized_student, normalized_correct)):
            is_correct = student == correct
            correct_count += 1 if is_correct else 0
            feedback.append(f"{'✅' if is_correct else '❌'} {correct_labels[i]}")

        score = (correct_count / len(correct_labels)) * 100
        return score, feedback

    def main():
        # Initialize database
        try:
            init_db()
            logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing database: {str(e)}")
            import os
            if os.path.exists('questions.db'):
                os.remove('questions.db')
                logger.info("Removed corrupted database file")
            init_db()
            logger.info("Database re-initialized successfully")

        # Create application
        application = ApplicationBuilder().token(BOT_TOKEN).build()

        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("categories", categories_command))
        application.add_handler(CommandHandler("stats", stats_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("ask", ask_command))

        # Add message handler for collecting answers
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, collect_answers))

        # Add callback query handlers
        application.add_handler(CallbackQueryHandler(show_main_categories, pattern="^main_categories$"))
        application.add_handler(CallbackQueryHandler(show_subcategories, pattern="^category_"))
        application.add_handler(CallbackQueryHandler(quiz, pattern="^subcategory_"))
        application.add_handler(CallbackQueryHandler(check_answer, pattern="^answer_"))
        application.add_handler(CallbackQueryHandler(show_stats, pattern="^show_stats$"))
        application.add_handler(CallbackQueryHandler(show_leaderboard, pattern="^leaderboard"))
        application.add_handler(CallbackQueryHandler(detailed_stats, pattern="^detailed_stats$"))
        application.add_handler(CallbackQueryHandler(study_guide, pattern="^study_guide$"))
        application.add_handler(CallbackQueryHandler(ask_help, pattern="^ask_help$"))
        application.add_handler(CallbackQueryHandler(donations, pattern="^donations$"))
        application.add_handler(CallbackQueryHandler(donation_complete, pattern="^donation_complete$"))
        application.add_handler(CallbackQueryHandler(about, pattern="^about$"))
        application.add_handler(CallbackQueryHandler(start_menu, pattern="^start_menu$"))
        application.add_handler(CallbackQueryHandler(image_quiz, pattern="^image_quiz$"))
        application.add_handler(CallbackQueryHandler(handle_cadaver_quiz, pattern="^cadaver_quiz$"))
        application.add_handler(CallbackQueryHandler(handle_histology_quiz, pattern="^histology_quiz$"))
        application.add_handler(CallbackQueryHandler(show_labels, pattern="^show_.*_labels$"))
        application.add_handler(CallbackQueryHandler(submit_answers, pattern="^submit_answers$"))
        application.add_handler(CallbackQueryHandler(get_hint, pattern="^get_hint$"))
        application.add_handler(CallbackQueryHandler(show_image_quiz_stats, pattern="^image_quiz_stats$"))

        # Start the Bot
        application.run_polling()

    if __name__ == "__main__":
        main()