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
    "Biostatistics": [],
    "Behavioral Science": [],
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

    # Check if user_stats table exists and what columns it has
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_stats'")
    if cursor.fetchone():
        # Table exists, check if it has all required columns
        cursor.execute("PRAGMA table_info(user_stats)")
        columns = [column[1] for column in cursor.fetchall()]
        
        # If gamification columns are missing, add them
        required_columns = [
            ('xp_points', 'INTEGER DEFAULT 0'),
            ('level', 'INTEGER DEFAULT 1'),
            ('daily_streak', 'INTEGER DEFAULT 0'),
            ('study_days', 'TEXT'),
            ('badges', 'TEXT'),
            ('spaced_repetition', 'TEXT'),
            ('weekly_challenge_score', 'INTEGER DEFAULT 0'),
            ('total_study_time', 'INTEGER DEFAULT 0'),
            ('daily_performance', 'TEXT'),
            ('topic_time_tracking', 'TEXT'),
            ('learning_curve_data', 'TEXT'),
            ('weakness_patterns', 'TEXT'),
            ('session_analytics', 'TEXT'),
            ('response_times', 'TEXT'),
            ('concept_mastery', 'TEXT')
        ]
        
        for column_name, column_def in required_columns:
            if column_name not in columns:
                try:
                    cursor.execute(f'ALTER TABLE user_stats ADD COLUMN {column_name} {column_def}')
                except sqlite3.OperationalError:
                    # Column might already exist, ignore error
                    pass
    else:
        # Create user_stats table with all columns
        cursor.execute('''
        CREATE TABLE user_stats (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            total_attempts INTEGER DEFAULT 0,
            correct_answers INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0,
            max_streak INTEGER DEFAULT 0,
            last_quiz_date TEXT,
            category_stats TEXT,
            xp_points INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            daily_streak INTEGER DEFAULT 0,
            study_days TEXT,
            badges TEXT,
            spaced_repetition TEXT,
            weekly_challenge_score INTEGER DEFAULT 0,
            total_study_time INTEGER DEFAULT 0
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
        self.xp_points = 0
        self.level = 1
        self.daily_streak = 0
        self.study_days = set()
        self.badges = set()
        self.spaced_repetition = {}  # question_id: {'interval': days, 'next_review': date, 'difficulty': 0-5}
        self.weekly_challenge_score = 0
        self.total_study_time = 0  # in minutes
        
        # Advanced Analytics Fields
        self.daily_performance = {}  # date: {'attempts': 0, 'correct': 0, 'time_spent': 0, 'topics': []}
        self.topic_time_tracking = {}  # topic: {'total_time': 0, 'questions': 0, 'avg_time_per_q': 0}
        self.learning_curve_data = {}  # topic: [{'date': date, 'accuracy': float, 'attempts': int}]
        self.weakness_patterns = {}  # topic: {'error_count': 0, 'common_mistakes': [], 'improvement_trend': []}
        self.session_analytics = []  # [{'date': date, 'duration': minutes, 'questions': int, 'accuracy': float}]
        self.response_times = {}  # question_id: [response_times] for tracking improvement
        self.concept_mastery = {}  # concept: {'mastery_level': 0-100, 'last_tested': date, 'progression': []}
        
        # Advanced AI Features
        self.learning_style = {'visual': 0, 'auditory': 0, 'kinesthetic': 0, 'reading_writing': 0}
        self.ai_generated_questions = []  # Store AI-generated practice questions
        self.concept_relationships = {}  # Concept mapping data
        self.tutoring_sessions = []  # AI tutoring interaction history
        self.personalized_explanations = {}  # Customized explanations based on learning style
        self.difficulty_adaptation = {}  # AI-driven difficulty adjustment

    def record_answer(self, question, is_correct, response_time=None, session_start=None):
        self.total_attempts += 1
        category = question['category']
        question_id = question['id']

        if category not in self.category_stats:
            self.category_stats[category] = {'attempts': 0, 'correct': 0}

        self.category_stats[category]['attempts'] += 1

        # Update daily streak
        today = time.strftime("%Y-%m-%d")
        if today not in self.study_days:
            self.study_days.add(today)
            if self.last_quiz_date == time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400)):
                self.daily_streak += 1
            else:
                self.daily_streak = 1

        # Advanced Analytics Tracking
        self._update_daily_performance(today, category, is_correct, response_time)
        self._update_topic_time_tracking(category, response_time)
        self._update_learning_curve(category, is_correct, today)
        self._update_weakness_patterns(category, is_correct, question)
        if response_time:
            self._track_response_time(question_id, response_time)
        self._update_concept_mastery(category, is_correct, today)

        if is_correct:
            self.correct_answers += 1
            self.category_stats[category]['correct'] += 1
            self.streak += 1
            self.max_streak = max(self.streak, self.max_streak)
            
            # XP and gamification rewards
            xp_earned = 10 + (self.streak * 2)  # Base 10 XP + streak bonus
            self.xp_points += xp_earned
            
            # Update spaced repetition - increase interval for correct answers
            if question_id in self.spaced_repetition:
                self.spaced_repetition[question_id]['difficulty'] = max(0, self.spaced_repetition[question_id]['difficulty'] - 1)
                self.spaced_repetition[question_id]['interval'] = min(30, self.spaced_repetition[question_id]['interval'] * 2)
            else:
                self.spaced_repetition[question_id] = {'interval': 1, 'difficulty': 0}
        else:
            self.streak = 0
            xp_earned = 2  # Small XP for attempt
            self.xp_points += xp_earned
            
            # Update spaced repetition - decrease interval for incorrect answers
            if question_id in self.spaced_repetition:
                self.spaced_repetition[question_id]['difficulty'] = min(5, self.spaced_repetition[question_id]['difficulty'] + 1)
                self.spaced_repetition[question_id]['interval'] = max(1, self.spaced_repetition[question_id]['interval'] // 2)
            else:
                self.spaced_repetition[question_id] = {'interval': 1, 'difficulty': 3}

        # Set next review date
        if question_id in self.spaced_repetition:
            next_review = time.time() + (self.spaced_repetition[question_id]['interval'] * 86400)
            self.spaced_repetition[question_id]['next_review'] = time.strftime("%Y-%m-%d", time.localtime(next_review))

        # Update level based on XP
        new_level = min(50, (self.xp_points // 100) + 1)
        if new_level > self.level:
            self.level = new_level
            self.badges.add(f"🌟 Level {new_level}")

        # Check for new badges
        self._check_badges()
        
        self.last_quiz_date = today

    def _check_badges(self):
        """Check and award new badges based on achievements"""
        # Study streak badges
        if self.daily_streak >= 7 and "🔥 Week Warrior" not in self.badges:
            self.badges.add("🔥 Week Warrior")
        if self.daily_streak >= 30 and "🏆 Month Master" not in self.badges:
            self.badges.add("🏆 Month Master")
        
        # Question count badges
        if self.total_attempts >= 25 and "📚 Beginner" not in self.badges:
            self.badges.add("📚 Beginner")
        if self.total_attempts >= 100 and "🎓 Scholar" not in self.badges:
            self.badges.add("🎓 Scholar")
        if self.total_attempts >= 500 and "🧠 Genius" not in self.badges:
            self.badges.add("🧠 Genius")
        
        # Accuracy badges
        accuracy = self.get_accuracy()
        if accuracy >= 90 and self.total_attempts >= 50 and "🎯 Perfectionist" not in self.badges:
            self.badges.add("🎯 Perfectionist")
        if accuracy >= 75 and self.total_attempts >= 20 and "✅ Consistent" not in self.badges:
            self.badges.add("✅ Consistent")
        
        # Streak badges
        if self.max_streak >= 10 and "🔥 Fire Streak" not in self.badges:
            self.badges.add("🔥 Fire Streak")
        if self.max_streak >= 25 and "⚡ Lightning Round" not in self.badges:
            self.badges.add("⚡ Lightning Round")
        
        # Category mastery badges
        for category, stats in self.category_stats.items():
            if stats['attempts'] >= 20:
                cat_accuracy = (stats['correct'] / stats['attempts']) * 100
                if cat_accuracy >= 85 and f"🏅 {category} Master" not in self.badges:
                    self.badges.add(f"🏅 {category} Master")

    def get_next_level_xp(self):
        """Get XP needed for next level"""
        return (self.level * 100) - self.xp_points

    def get_level_progress(self):
        """Get progress percentage to next level"""
        current_level_xp = (self.level - 1) * 100
        next_level_xp = self.level * 100
        progress_xp = self.xp_points - current_level_xp
        return (progress_xp / 100) * 100

    def get_questions_for_review(self):
        """Get questions that need review based on spaced repetition"""
        today = time.strftime("%Y-%m-%d")
        review_questions = []
        
        for question_id, data in self.spaced_repetition.items():
            if data.get('next_review', today) <= today:
                review_questions.append({
                    'question_id': question_id,
                    'difficulty': data['difficulty'],
                    'interval': data['interval']
                })
        
        # Sort by difficulty (hardest first) then by interval (shortest first)
        review_questions.sort(key=lambda x: (x['difficulty'], -x['interval']), reverse=True)
        return review_questions

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

    def _update_daily_performance(self, date, topic, is_correct, response_time):
        """Track daily performance metrics"""
        if date not in self.daily_performance:
            self.daily_performance[date] = {'attempts': 0, 'correct': 0, 'time_spent': 0, 'topics': set()}
        
        self.daily_performance[date]['attempts'] += 1
        if is_correct:
            self.daily_performance[date]['correct'] += 1
        if response_time:
            self.daily_performance[date]['time_spent'] += response_time
        self.daily_performance[date]['topics'].add(topic)

    def _update_topic_time_tracking(self, topic, response_time):
        """Track time spent per topic"""
        if topic not in self.topic_time_tracking:
            self.topic_time_tracking[topic] = {'total_time': 0, 'questions': 0, 'avg_time_per_q': 0}
        
        if response_time:
            self.topic_time_tracking[topic]['total_time'] += response_time
        self.topic_time_tracking[topic]['questions'] += 1
        
        if self.topic_time_tracking[topic]['questions'] > 0:
            self.topic_time_tracking[topic]['avg_time_per_q'] = (
                self.topic_time_tracking[topic]['total_time'] / 
                self.topic_time_tracking[topic]['questions']
            )

    def _update_learning_curve(self, topic, is_correct, date):
        """Track learning progression over time"""
        if topic not in self.learning_curve_data:
            self.learning_curve_data[topic] = []
        
        # Find or create today's entry
        today_entry = next((entry for entry in self.learning_curve_data[topic] if entry['date'] == date), None)
        if not today_entry:
            today_entry = {'date': date, 'attempts': 0, 'correct': 0, 'accuracy': 0}
            self.learning_curve_data[topic].append(today_entry)
        
        today_entry['attempts'] += 1
        if is_correct:
            today_entry['correct'] += 1
        today_entry['accuracy'] = (today_entry['correct'] / today_entry['attempts']) * 100

    def _update_weakness_patterns(self, topic, is_correct, question):
        """Identify and track weakness patterns"""
        if topic not in self.weakness_patterns:
            self.weakness_patterns[topic] = {'error_count': 0, 'common_mistakes': [], 'improvement_trend': []}
        
        if not is_correct:
            self.weakness_patterns[topic]['error_count'] += 1
            # Track common mistake patterns
            mistake_type = self._categorize_mistake(question)
            self.weakness_patterns[topic]['common_mistakes'].append(mistake_type)
        
        # Track improvement trend (last 10 attempts)
        self.weakness_patterns[topic]['improvement_trend'].append(is_correct)
        if len(self.weakness_patterns[topic]['improvement_trend']) > 10:
            self.weakness_patterns[topic]['improvement_trend'].pop(0)

    def _track_response_time(self, question_id, response_time):
        """Track response times for individual questions"""
        if question_id not in self.response_times:
            self.response_times[question_id] = []
        
        self.response_times[question_id].append(response_time)
        # Keep only last 5 response times
        if len(self.response_times[question_id]) > 5:
            self.response_times[question_id].pop(0)

    def _update_concept_mastery(self, concept, is_correct, date):
        """Track concept mastery progression"""
        if concept not in self.concept_mastery:
            self.concept_mastery[concept] = {'mastery_level': 0, 'last_tested': date, 'progression': []}
        
        # Update mastery level based on performance
        if is_correct:
            self.concept_mastery[concept]['mastery_level'] = min(100, self.concept_mastery[concept]['mastery_level'] + 5)
        else:
            self.concept_mastery[concept]['mastery_level'] = max(0, self.concept_mastery[concept]['mastery_level'] - 3)
        
        self.concept_mastery[concept]['last_tested'] = date
        self.concept_mastery[concept]['progression'].append({
            'date': date,
            'mastery': self.concept_mastery[concept]['mastery_level'],
            'correct': is_correct
        })

    def _categorize_mistake(self, question):
        """Categorize types of mistakes for pattern analysis"""
        # Simple categorization based on question content
        question_text = question.get('question', '').lower()
        
        if any(word in question_text for word in ['anatomy', 'structure', 'location']):
            return 'anatomy_structure'
        elif any(word in question_text for word in ['function', 'physiology', 'process']):
            return 'physiology_function'
        elif any(word in question_text for word in ['nerve', 'innervation', 'nervous']):
            return 'nervous_system'
        elif any(word in question_text for word in ['blood', 'circulation', 'heart']):
            return 'cardiovascular'
        else:
            return 'general_concept'

    def analyze_learning_style(self, question_type, response_time, is_correct):
        """Analyze and update learning style preferences based on performance"""
        # Visual learning indicators
        if 'image' in question_type.lower() or 'diagram' in question_type.lower():
            if is_correct and response_time < 30:  # Quick correct response to visual content
                self.learning_style['visual'] += 2
            elif is_correct:
                self.learning_style['visual'] += 1
        
        # Reading/writing learning indicators
        if 'definition' in question_type.lower() or 'text' in question_type.lower():
            if is_correct and response_time < 45:
                self.learning_style['reading_writing'] += 2
            elif is_correct:
                self.learning_style['reading_writing'] += 1
        
        # Kinesthetic learning indicators (interactive elements)
        if 'interactive' in question_type.lower() or 'simulation' in question_type.lower():
            if is_correct:
                self.learning_style['kinesthetic'] += 1
        
        # Normalize learning style scores
        total_score = sum(self.learning_style.values())
        if total_score > 0:
            for style in self.learning_style:
                self.learning_style[style] = (self.learning_style[style] / total_score) * 100

    def get_dominant_learning_style(self):
        """Get the user's dominant learning style"""
        if not any(self.learning_style.values()):
            return 'balanced'
        return max(self.learning_style, key=self.learning_style.get)

    def get_learning_insights(self):
        """Generate learning insights and recommendations"""
        insights = {
            'strengths': [],
            'weaknesses': [],
            'recommendations': [],
            'progress_trend': 'stable'
        }
        
        # Analyze strengths and weaknesses
        for topic, stats in self.category_stats.items():
            if stats['attempts'] >= 5:  # Minimum attempts for meaningful analysis
                accuracy = (stats['correct'] / stats['attempts']) * 100
                if accuracy >= 80:
                    insights['strengths'].append(f"{topic} ({accuracy:.1f}%)")
                elif accuracy < 60:
                    insights['weaknesses'].append(f"{topic} ({accuracy:.1f}%)")
        
        # Generate recommendations
        for topic, weakness in self.weakness_patterns.items():
            if weakness['error_count'] >= 3:
                recent_trend = weakness['improvement_trend'][-5:] if len(weakness['improvement_trend']) >= 5 else weakness['improvement_trend']
                if sum(recent_trend) / len(recent_trend) < 0.6:  # Less than 60% recent accuracy
                    insights['recommendations'].append(f"Focus more practice on {topic}")
        
        return insights

    def get_peer_comparison_data(self):
        """Get anonymized data for peer comparison"""
        return {
            'overall_accuracy': self.get_accuracy(),
            'total_questions': self.total_attempts,
            'study_streak': self.daily_streak,
            'level': self.level,
            'categories_mastered': len([cat for cat, stats in self.category_stats.items() 
                                      if stats['attempts'] >= 10 and (stats['correct']/stats['attempts']) >= 0.8])
        }

def save_user_stats(user_id, username, first_name, quiz_session):
    conn = sqlite3.connect('questions.db')
    cursor = conn.cursor()

    # Check which columns exist in the table
    cursor.execute("PRAGMA table_info(user_stats)")
    columns = [column[1] for column in cursor.fetchall()]
    
    # Build the query based on available columns
    if 'xp_points' in columns:
        # New schema with gamification features
        cursor.execute('''
        INSERT OR REPLACE INTO user_stats
        (user_id, username, first_name, total_attempts, correct_answers, streak, max_streak, last_quiz_date, category_stats, xp_points, level, daily_streak, study_days, badges, spaced_repetition, weekly_challenge_score, total_study_time, daily_performance, topic_time_tracking, learning_curve_data, weakness_patterns, session_analytics, response_times, concept_mastery)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            username,
            first_name,
            quiz_session.total_attempts,
            quiz_session.correct_answers,
            quiz_session.streak,
            quiz_session.max_streak,
            quiz_session.last_quiz_date,
            json.dumps(quiz_session.category_stats),
            quiz_session.xp_points,
            quiz_session.level,
            quiz_session.daily_streak,
            json.dumps(list(quiz_session.study_days)),
            json.dumps(list(quiz_session.badges)),
            json.dumps(quiz_session.spaced_repetition),
            quiz_session.weekly_challenge_score,
            quiz_session.total_study_time,
            json.dumps(quiz_session.daily_performance),
            json.dumps(quiz_session.topic_time_tracking),
            json.dumps(quiz_session.learning_curve_data),
            json.dumps(quiz_session.weakness_patterns),
            json.dumps(quiz_session.session_analytics),
            json.dumps(quiz_session.response_times),
            json.dumps(quiz_session.concept_mastery)
        ))
    else:
        # Old schema without gamification features
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
            quiz_session.total_attempts = result[3] if result[3] else 0
            quiz_session.correct_answers = result[4] if result[4] else 0
            quiz_session.streak = result[5] if result[5] else 0
            quiz_session.max_streak = result[6] if result[6] else 0
            quiz_session.last_quiz_date = result[7]
            quiz_session.category_stats = json.loads(result[8]) if result[8] else {}
            
            # Load gamification data with fallbacks for older records
            if len(result) > 9:
                quiz_session.xp_points = result[9] if result[9] else 0
                quiz_session.level = result[10] if result[10] else 1
                quiz_session.daily_streak = result[11] if result[11] else 0
                quiz_session.study_days = set(json.loads(result[12])) if result[12] else set()
                quiz_session.badges = set(json.loads(result[13])) if result[13] else set()
                quiz_session.spaced_repetition = json.loads(result[14]) if result[14] else {}
                quiz_session.weekly_challenge_score = result[15] if result[15] else 0
                quiz_session.total_study_time = result[16] if result[16] else 0
                
                # Load advanced analytics data with fallbacks
                if len(result) > 17:
                    quiz_session.daily_performance = json.loads(result[17]) if result[17] else {}
                    quiz_session.topic_time_tracking = json.loads(result[18]) if result[18] else {}
                    quiz_session.learning_curve_data = json.loads(result[19]) if result[19] else {}
                    quiz_session.weakness_patterns = json.loads(result[20]) if result[20] else {}
                    quiz_session.session_analytics = json.loads(result[21]) if result[21] else []
                    quiz_session.response_times = json.loads(result[22]) if result[22] else {}
                    quiz_session.concept_mastery = json.loads(result[23]) if result[23] else {}
            
            return quiz_session

        return QuizSession()
    except Exception as e:
        logger.error(f"Error loading user stats: {str(e)}")
        return QuizSession()

def get_random_question(category=None, user_session=None):
    conn = sqlite3.connect('questions.db')
    cursor = conn.cursor()

    # Log the request for debugging
    logger.info(f"Getting question for category: {category}")

    # Check for spaced repetition questions first
    if user_session:
        review_questions = user_session.get_questions_for_review()
        if review_questions:
            # 30% chance to show a review question
            if random.random() < 0.3:
                review_q = review_questions[0]
                cursor.execute('SELECT * FROM questions WHERE id = ?', (review_q['question_id'],))
                question = cursor.fetchone()
                if question:
                    conn.close()
                    return {
                        'id': question[0],
                        'question': question[1] + " 🔄 (Review)",
                        'answer': bool(question[2]),
                        'explanation': question[3],
                        'ai_explanation': question[4],
                        'references': json.loads(question[5] if question[5] else "{}"),
                        'category': question[6],
                        'is_review': True
                    }

    if category and category != "All Categories":
        # Make sure we're getting questions ONLY from the exact category requested
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
            'category': question[6],
            'is_review': False
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

def get_peer_averages():
    """Calculate community averages for peer comparison."""
    try:
        conn = sqlite3.connect('questions.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT total_attempts, correct_answers, daily_streak, level FROM user_stats WHERE total_attempts > 0')
        users_data = cursor.fetchall()
        conn.close()
        
        if not users_data:
            return {
                'avg_accuracy': 50.0,
                'avg_questions': 10,
                'avg_streak': 1,
                'avg_level': 1
            }
        
        total_users = len(users_data)
        avg_accuracy = sum((correct/attempts)*100 for attempts, correct, _, _ in users_data if attempts > 0) / total_users
        avg_questions = sum(attempts for attempts, _, _, _ in users_data) / total_users
        avg_streak = sum(streak for _, _, streak, _ in users_data) / total_users
        avg_level = sum(level for _, _, _, level in users_data) / total_users
        
        return {
            'avg_accuracy': avg_accuracy,
            'avg_questions': avg_questions,
            'avg_streak': avg_streak,
            'avg_level': avg_level
        }
    except Exception as e:
        logger.error(f"Error calculating peer averages: {str(e)}")
        return {
            'avg_accuracy': 50.0,
            'avg_questions': 10,
            'avg_streak': 1,
            'avg_level': 1
        }

def calculate_user_percentile(user_data, peer_averages):
    """Calculate user's percentile ranking."""
    # Simple percentile calculation based on overall performance
    accuracy_score = min(100, user_data['overall_accuracy'] / peer_averages['avg_accuracy'] * 50)
    questions_score = min(100, user_data['total_questions'] / peer_averages['avg_questions'] * 30)
    streak_score = min(100, user_data['study_streak'] / max(1, peer_averages['avg_streak']) * 20)
    
    total_score = accuracy_score + questions_score + streak_score
    percentile = min(99, total_score)
    
    return percentile

async def concept_mastery_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    quiz_session = context.user_data.get('quiz_session')
    if not quiz_session:
        quiz_session = load_user_stats(user.id)
        context.user_data['quiz_session'] = quiz_session

    message = (
        f"*🧠 {user.first_name}'s Concept Mastery*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*Mastery Levels by Concept:*\n\n"
    )

    if quiz_session.concept_mastery:
        # Sort concepts by mastery level
        sorted_concepts = sorted(quiz_session.concept_mastery.items(), 
                               key=lambda x: x[1]['mastery_level'], reverse=True)
        
        for concept, mastery_data in sorted_concepts:
            mastery_level = mastery_data['mastery_level']
            last_tested = mastery_data['last_tested']
            
            # Mastery level indicators
            if mastery_level >= 80:
                level_emoji = "🟢"
                level_text = "Mastered"
            elif mastery_level >= 60:
                level_emoji = "🟡"
                level_text = "Good"
            elif mastery_level >= 40:
                level_emoji = "🟠"
                level_text = "Developing"
            else:
                level_emoji = "🔴"
                level_text = "Needs Work"
            
            progress_bar = "█" * (mastery_level // 10) + "▒" * (10 - mastery_level // 10)
            
            message += f"{level_emoji} *{concept}*\n"
            message += f"   {progress_bar} {mastery_level}% ({level_text})\n"
            message += f"   Last tested: {last_tested}\n\n"

        # Mastery summary
        mastered_count = sum(1 for _, data in quiz_session.concept_mastery.items() if data['mastery_level'] >= 80)
        total_concepts = len(quiz_session.concept_mastery)
        
        message += f"*📊 Mastery Summary:*\n"
        message += f"Concepts Mastered: {mastered_count}/{total_concepts}\n"
        message += f"Overall Mastery: {(mastered_count/total_concepts)*100:.1f}%\n"
    else:
        message += "Start practicing to track your concept mastery progress!\n"

    keyboard = [
        [InlineKeyboardButton("🔙 Analytics Menu", callback_data="advanced_analytics")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def performance_trends(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    quiz_session = context.user_data.get('quiz_session')
    if not quiz_session:
        quiz_session = load_user_stats(user.id)
        context.user_data['quiz_session'] = quiz_session

    message = (
        f"*📅 {user.first_name}'s Performance Trends*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    if quiz_session.daily_performance:
        # Get last 7 days of data
        recent_days = sorted(quiz_session.daily_performance.keys())[-7:]
        
        message += "*📊 Last 7 Days Performance:*\n\n"
        
        for day in recent_days:
            day_data = quiz_session.daily_performance[day]
            accuracy = (day_data['correct'] / day_data['attempts'] * 100) if day_data['attempts'] > 0 else 0
            time_minutes = day_data['time_spent'] / 60
            
            # Format date nicely
            day_name = datetime.strptime(day, "%Y-%m-%d").strftime("%a %m/%d")
            
            accuracy_emoji = "🟢" if accuracy >= 80 else "🟡" if accuracy >= 60 else "🔴"
            
            message += f"{accuracy_emoji} *{day_name}*\n"
            message += f"   Questions: {day_data['attempts']}\n"
            message += f"   Accuracy: {accuracy:.1f}%\n"
            message += f"   Time: {time_minutes:.1f}min\n"
            message += f"   Topics: {len(day_data.get('topics', []))}\n\n"

        # Weekly trends
        if len(recent_days) >= 2:
            recent_accuracy = []
            for day in recent_days:
                day_data = quiz_session.daily_performance[day]
                if day_data['attempts'] > 0:
                    accuracy = (day_data['correct'] / day_data['attempts'] * 100)
                    recent_accuracy.append(accuracy)
            
            if len(recent_accuracy) >= 2:
                trend = recent_accuracy[-1] - recent_accuracy[0]
                trend_emoji = "📈" if trend > 5 else "📉" if trend < -5 else "➡️"
                message += f"*{trend_emoji} Weekly Trend:* {trend:+.1f}%\n"

    else:
        message += "No daily performance data available yet.\nStart your learning journey to see trends!\n"

    keyboard = [
        [InlineKeyboardButton("🔙 Analytics Menu", callback_data="advanced_analytics")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # Load user stats
    user_id = user.id
    quiz_session = load_user_stats(user_id)
    context.user_data['quiz_session'] = quiz_session

    # Check if user has questions to review
    review_count = len(quiz_session.get_questions_for_review())
    level_progress = quiz_session.get_level_progress()
    
    welcome_message = (
        f"🩺 *Hi, {user.first_name}! Welcome to {BOT_NAME}* 🩺\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Your interactive medical learning companion!\n\n"
        f"🌟 *LEVEL {quiz_session.level}* | XP: {quiz_session.xp_points}\n"
        f"📊 Progress: {'█' * int(level_progress/10)}{'▒' * (10-int(level_progress/10))} {level_progress:.0f}%\n"
        f"🔥 Study Streak: {quiz_session.daily_streak} days\n"
        f"🔄 Questions to Review: {review_count}\n\n"
        "🎯 *KEY FEATURES*\n"
        "📚 Comprehensive Medical Quizzes\n"
        "📊 Smart Spaced Repetition\n"
        "🏆 Achievements & Badges\n"
        "🧠 AI-Powered Explanations\n\n"
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
            InlineKeyboardButton("🤖 AI Tutoring", callback_data="ai_tutoring"),
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
        [InlineKeyboardButton("📊 Biostatistics", callback_data="category_Biostatistics")],
        [InlineKeyboardButton("🧠 Behavioral Science", callback_data="category_Behavioral Science")],
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

    # If no subcategories (like Biostatistics and Behavioral Science), go directly to quiz
    if not subcategories:
        await quiz(update, context, category=main_category)
        return

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

    # Get user session for spaced repetition
    user_session = context.user_data.get('quiz_session')
    question = get_random_question(category, user_session)
    if not question:
        await query.edit_message_text(
            "No questions available for this category.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="main_categories")
            ]])
        )
        return

    context.user_data['current_question'] = question
    context.user_data['question_start_time'] = time.time()

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

    # Calculate response time
    question_start_time = context.user_data.get('question_start_time', time.time())
    response_time = time.time() - question_start_time
    
    is_correct = user_answer == current_question['answer']
    quiz_session = context.user_data.get('quiz_session', QuizSession())
    quiz_session.record_answer(current_question, is_correct, response_time)
    context.user_data['quiz_session'] = quiz_session

    # Save user stats
    save_user_stats(user.id, user.username, user.first_name, quiz_session)

    # Calculate XP earned
    xp_gained = 10 + (quiz_session.streak * 2) if is_correct else 2
    level_up = quiz_session.level > ((quiz_session.xp_points - xp_gained) // 100 + 1)
    
    # Generate personalized explanation based on learning style
    learning_style = quiz_session.get_dominant_learning_style()
    personalized_explanation = await generate_personalized_explanation(
        current_question['question'], learning_style, is_correct
    )
    
    response = (
        f"{'✅ Correct!' if is_correct else '❌ Incorrect!'}\n\n"
        f"*XP Gained:* +{xp_gained} 🌟\n"
        f"*Current Streak:* {quiz_session.streak} 🔥\n"
        f"*Level:* {quiz_session.level} | XP: {quiz_session.xp_points}\n"
    )
    
    if level_up:
        response += f"🎉 *LEVEL UP!* Welcome to Level {quiz_session.level}!\n"
    
    if current_question.get('is_review'):
        response += "🔄 *Review Question Completed!*\n"
    
    response += (
        f"\n*Question:*\n{current_question['question'].replace(' 🔄 (Review)', '')}\n\n"
        f"*Standard Explanation:*\n{current_question['explanation']}\n\n"
    )

    # Add personalized AI explanation if generated
    if personalized_explanation:
        style_emoji = {'visual': '👁️', 'auditory': '🎵', 'kinesthetic': '✋', 'reading_writing': '📝', 'balanced': '⚖️'}
        response += f"*{style_emoji.get(learning_style, '🧠')} Personalized Explanation ({learning_style.title()} Style):*\n{personalized_explanation}\n\n"
    elif current_question.get('ai_explanation'):
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

    # Get gamification stats
    level_progress = quiz_session.get_level_progress()
    next_level_xp = quiz_session.get_next_level_xp()
    review_count = len(quiz_session.get_questions_for_review())
    
    stats_message = (
        f"📚 *{user.first_name}'s Medical Knowledge Journey* 📚\n"
        "═══════════════════════\n\n"
        f"🌟 *Level {quiz_session.level}* | XP: {quiz_session.xp_points}\n"
        f"📊 Progress: {'█' * int(level_progress/10)}{'▒' * (10-int(level_progress/10))} {level_progress:.0f}%\n"
        f"🎯 Next Level: {next_level_xp} XP needed\n\n"
        f"{performance_emoji} *Overall Performance*\n"
        f"• Questions Attempted: {quiz_session.total_attempts}\n"
        f"• Correct Answers: {quiz_session.correct_answers}\n"
        f"• Overall Accuracy: {accuracy:.1f}%\n"
        f"• Current Answer Streak: {quiz_session.streak} 🔥\n"
        f"• Best Answer Streak: {quiz_session.max_streak} ⭐\n"
        f"• Daily Study Streak: {quiz_session.daily_streak} days 🔥\n"
        f"• Questions for Review: {review_count} 🔄\n\n"
        "*📊 Category Breakdown*\n"
    )

    for category, stats in quiz_session.category_stats.items():
        cat_accuracy = quiz_session.get_category_accuracy(category)
        progress_bar = "▰" * int(cat_accuracy/10) + "▱" * (10 - int(cat_accuracy/10))
        stats_message += f"\n{category}:\n{progress_bar} {cat_accuracy:.1f}%\n"

    # Show recent badges
    recent_badges = list(quiz_session.badges)[-5:]  # Show last 5 badges
    if recent_badges:
        stats_message += "\n*🏆 Recent Badges*\n"
        for badge in recent_badges:
            stats_message += f"• {badge}\n"
    
    # Show motivational message
    progress_bar = "█" * int(accuracy/10) + "▒" * (10 - int(accuracy/10))
    if accuracy >= 80:
        stats_message += f"\n\n📊 Progress: [{progress_bar}] {accuracy:.1f}%\n"
        stats_message += "🌟 Outstanding performance! Keep shining!"
    elif accuracy >= 60:
        stats_message += "\n\n💪 Great progress! Keep pushing!"
    else:
        stats_message += "\n\n📚 Keep learning! You're on the right path!"
    
    # Daily challenge reminder
    if quiz_session.daily_streak > 0:
        stats_message += f"\n\n🔥 Keep your {quiz_session.daily_streak}-day streak alive!"

    keyboard = [
        [InlineKeyboardButton("📚 Continue Learning", callback_data="main_categories")],
        [InlineKeyboardButton("📊 Detailed Analysis", callback_data="detailed_stats")],
        [InlineKeyboardButton("🏆 View All Badges", callback_data="view_badges")],
        [InlineKeyboardButton("🔄 Spaced Review", callback_data="spaced_review")]
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

async def view_badges(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    quiz_session = context.user_data.get('quiz_session')
    if not quiz_session:
        quiz_session = load_user_stats(user.id)
        context.user_data['quiz_session'] = quiz_session

    badges_list = list(quiz_session.badges)
    
    if not badges_list:
        message = (
            f"🏆 *{user.first_name}'s Badge Collection* 🏆\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "No badges earned yet! Keep studying to unlock achievements.\n\n"
            "*Available Badges:*\n"
            "📚 Beginner - Answer 25 questions\n"
            "🎓 Scholar - Answer 100 questions\n"
            "🧠 Genius - Answer 500 questions\n"
            "🔥 Week Warrior - 7-day study streak\n"
            "🏆 Month Master - 30-day study streak\n"
            "✅ Consistent - 75%+ accuracy (20+ questions)\n"
            "🎯 Perfectionist - 90%+ accuracy (50+ questions)\n"
            "🔥 Fire Streak - 10+ answer streak\n"
            "⚡ Lightning Round - 25+ answer streak\n"
            "🏅 Category Master - 85%+ in any category (20+ attempts)\n"
            "🌟 Level Badges - Reach higher levels"
        )
    else:
        message = (
            f"🏆 *{user.first_name}'s Badge Collection* 🏆\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"*Badges Earned: {len(badges_list)}*\n\n"
        )
        
        # Group badges by type
        level_badges = [b for b in badges_list if "Level" in b]
        streak_badges = [b for b in badges_list if any(word in b for word in ["Warrior", "Master", "Fire", "Lightning"])]
        achievement_badges = [b for b in badges_list if b not in level_badges and b not in streak_badges]
        
        if level_badges:
            message += "*🌟 Level Badges:*\n"
            for badge in level_badges:
                message += f"• {badge}\n"
            message += "\n"
        
        if streak_badges:
            message += "*🔥 Streak Badges:*\n"
            for badge in streak_badges:
                message += f"• {badge}\n"
            message += "\n"
        
        if achievement_badges:
            message += "*🎯 Achievement Badges:*\n"
            for badge in achievement_badges:
                message += f"• {badge}\n"
    
    keyboard = [
        [InlineKeyboardButton("🔙 Back to Stats", callback_data="show_stats")],
        [InlineKeyboardButton("📚 Continue Learning", callback_data="main_categories")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def spaced_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    quiz_session = context.user_data.get('quiz_session')
    if not quiz_session:
        quiz_session = load_user_stats(user.id)
        context.user_data['quiz_session'] = quiz_session

    review_questions = quiz_session.get_questions_for_review()
    
    if not review_questions:
        message = (
            "🔄 *Spaced Repetition Review* 🔄\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🎉 No questions need review right now!\n\n"
            "The spaced repetition system automatically schedules review of questions you've answered incorrectly. Come back later or continue with regular quizzes to build up your review queue.\n\n"
            "*How it works:*\n"
            "• Incorrect answers → shorter review intervals\n"
            "• Correct answers → longer review intervals\n"
            "• Difficult questions reviewed more frequently\n"
            "• Mastered questions reviewed less often"
        )
        
        keyboard = [
            [InlineKeyboardButton("📚 Regular Quiz", callback_data="main_categories")],
            [InlineKeyboardButton("🔙 Back to Stats", callback_data="show_stats")]
        ]
    else:
        message = (
            "🔄 *Spaced Repetition Review* 🔄\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📋 **{len(review_questions)} questions** ready for review!\n\n"
            "*Review Priority:*\n"
            f"🔴 High Priority: {len([q for q in review_questions if q['difficulty'] >= 4])}\n"
            f"🟡 Medium Priority: {len([q for q in review_questions if 2 <= q['difficulty'] < 4])}\n"
            f"🟢 Low Priority: {len([q for q in review_questions if q['difficulty'] < 2])}\n\n"
            "Start your review session to strengthen weak areas and improve retention!"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔄 Start Review Session", callback_data="start_review_session")],
            [InlineKeyboardButton("📚 Regular Quiz", callback_data="main_categories")],
            [InlineKeyboardButton("🔙 Back to Stats", callback_data="show_stats")]
        ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def start_review_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Set review mode
    context.user_data['review_mode'] = True
    
    # Start quiz with review questions
    await quiz(update, context, category="Review")

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
        [InlineKeyboardButton("📈 Advanced Analytics", callback_data="advanced_analytics")],
        [InlineKeyboardButton("📚 Continue Learning", callback_data="main_categories")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def advanced_analytics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    message = (
        "*📈 ADVANCED ANALYTICS DASHBOARD*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Choose an analytics view to explore your learning journey in detail:\n\n"
        "📊 *Learning Curve* - Track improvement over time\n"
        "⏱️ *Time Analysis* - See time spent per topic\n"
        "🎯 *Weakness Analysis* - Identify areas for improvement\n"
        "👥 *Peer Comparison* - Compare with other learners\n"
        "🧠 *Concept Mastery* - Track understanding progression\n"
        "📅 *Performance Trends* - Daily and weekly patterns"
    )

    keyboard = [
        [InlineKeyboardButton("📊 Learning Curve", callback_data="learning_curve"),
         InlineKeyboardButton("⏱️ Time Analysis", callback_data="time_analysis")],
        [InlineKeyboardButton("🎯 Weakness Analysis", callback_data="weakness_analysis"),
         InlineKeyboardButton("👥 Peer Comparison", callback_data="peer_comparison")],
        [InlineKeyboardButton("🧠 Concept Mastery", callback_data="concept_mastery"),
         InlineKeyboardButton("📅 Performance Trends", callback_data="performance_trends")],
        [InlineKeyboardButton("🔙 Back to Stats", callback_data="detailed_stats")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def learning_curve_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    quiz_session = context.user_data.get('quiz_session')
    if not quiz_session:
        quiz_session = load_user_stats(user.id)
        context.user_data['quiz_session'] = quiz_session

    message = (
        f"*📊 {user.first_name}'s Learning Curve Analysis*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*Progress Visualization:*\n\n"
    )

    # Analyze learning curve data
    if quiz_session.learning_curve_data:
        for topic, curve_data in quiz_session.learning_curve_data.items():
            if len(curve_data) >= 2:  # Need at least 2 data points
                latest_accuracy = curve_data[-1]['accuracy']
                first_accuracy = curve_data[0]['accuracy']
                improvement = latest_accuracy - first_accuracy
                
                trend_emoji = "📈" if improvement > 5 else "📉" if improvement < -5 else "➡️"
                message += f"{trend_emoji} *{topic}*\n"
                message += f"   Current: {latest_accuracy:.1f}%\n"
                message += f"   Progress: {improvement:+.1f}%\n"
                message += f"   Sessions: {len(curve_data)}\n\n"
    else:
        message += "Not enough data yet. Keep practicing to see your learning curves!\n\n"

    # Overall learning insights
    insights = quiz_session.get_learning_insights()
    if insights['strengths']:
        message += "*🎯 Your Strengths:*\n"
        for strength in insights['strengths'][:3]:  # Top 3
            message += f"• {strength}\n"
        message += "\n"

    if insights['weaknesses']:
        message += "*📚 Focus Areas:*\n"
        for weakness in insights['weaknesses'][:3]:  # Top 3
            message += f"• {weakness}\n"
        message += "\n"

    keyboard = [
        [InlineKeyboardButton("🔙 Analytics Menu", callback_data="advanced_analytics")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def time_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    quiz_session = context.user_data.get('quiz_session')
    if not quiz_session:
        quiz_session = load_user_stats(user.id)
        context.user_data['quiz_session'] = quiz_session

    message = (
        f"*⏱️ {user.first_name}'s Time Analysis*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*Time Investment per Topic:*\n\n"
    )

    if quiz_session.topic_time_tracking:
        # Sort topics by time spent
        sorted_topics = sorted(quiz_session.topic_time_tracking.items(), 
                             key=lambda x: x[1]['total_time'], reverse=True)
        
        for topic, time_data in sorted_topics[:5]:  # Top 5 topics
            total_minutes = time_data['total_time'] / 60  # Convert to minutes
            avg_time = time_data['avg_time_per_q']
            questions = time_data['questions']
            
            message += f"📖 *{topic}*\n"
            message += f"   Total Time: {total_minutes:.1f} minutes\n"
            message += f"   Questions: {questions}\n"
            message += f"   Avg per Q: {avg_time:.1f}s\n\n"

        # Time efficiency analysis
        message += "*⚡ Efficiency Insights:*\n"
        fastest_topic = min(sorted_topics, key=lambda x: x[1]['avg_time_per_q']) if sorted_topics else None
        slowest_topic = max(sorted_topics, key=lambda x: x[1]['avg_time_per_q']) if sorted_topics else None
        
        if fastest_topic:
            message += f"🚀 Fastest: {fastest_topic[0]} ({fastest_topic[1]['avg_time_per_q']:.1f}s/q)\n"
        if slowest_topic:
            message += f"🐌 Needs Focus: {slowest_topic[0]} ({slowest_topic[1]['avg_time_per_q']:.1f}s/q)\n"
    else:
        message += "No time tracking data available yet. Start answering questions to see your time patterns!\n"

    keyboard = [
        [InlineKeyboardButton("🔙 Analytics Menu", callback_data="advanced_analytics")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def weakness_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    quiz_session = context.user_data.get('quiz_session')
    if not quiz_session:
        quiz_session = load_user_stats(user.id)
        context.user_data['quiz_session'] = quiz_session

    message = (
        f"*🎯 {user.first_name}'s Weakness Analysis*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    if quiz_session.weakness_patterns:
        message += "*🔍 Areas Needing Attention:*\n\n"
        
        # Sort by error count
        sorted_weaknesses = sorted(quiz_session.weakness_patterns.items(), 
                                 key=lambda x: x[1]['error_count'], reverse=True)
        
        for topic, weakness_data in sorted_weaknesses[:5]:
            error_count = weakness_data['error_count']
            improvement_trend = weakness_data['improvement_trend']
            
            if error_count >= 2:  # Only show significant weaknesses
                recent_performance = sum(improvement_trend[-5:]) / len(improvement_trend[-5:]) if improvement_trend else 0
                trend_emoji = "📈" if recent_performance > 0.6 else "📉" if recent_performance < 0.4 else "➡️"
                
                message += f"{trend_emoji} *{topic}*\n"
                message += f"   Errors: {error_count}\n"
                message += f"   Recent Trend: {recent_performance*100:.1f}%\n"
                
                # Common mistake patterns
                common_mistakes = weakness_data.get('common_mistakes', [])
                if common_mistakes:
                    mistake_counts = {}
                    for mistake in common_mistakes:
                        mistake_counts[mistake] = mistake_counts.get(mistake, 0) + 1
                    most_common = max(mistake_counts, key=mistake_counts.get)
                    message += f"   Pattern: {most_common.replace('_', ' ').title()}\n"
                
                message += "\n"

        # Improvement suggestions
        insights = quiz_session.get_learning_insights()
        if insights['recommendations']:
            message += "*💡 Improvement Suggestions:*\n"
            for rec in insights['recommendations'][:3]:
                message += f"• {rec}\n"
    else:
        message += "Great job! No significant weakness patterns detected yet.\nKeep practicing to maintain your strong performance! 🎉"

    keyboard = [
        [InlineKeyboardButton("🔙 Analytics Menu", callback_data="advanced_analytics")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def peer_comparison(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    quiz_session = context.user_data.get('quiz_session')
    if not quiz_session:
        quiz_session = load_user_stats(user.id)
        context.user_data['quiz_session'] = quiz_session

    # Get user's performance data
    user_data = quiz_session.get_peer_comparison_data()
    
    # Get anonymized peer data
    peer_averages = get_peer_averages()

    message = (
        f"*👥 {user.first_name}'s Peer Comparison*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*Your Performance vs. Community Average:*\n\n"
    )

    # Compare accuracy
    accuracy_diff = user_data['overall_accuracy'] - peer_averages['avg_accuracy']
    accuracy_emoji = "🟢" if accuracy_diff > 5 else "🟡" if accuracy_diff > -5 else "🔴"
    message += f"{accuracy_emoji} *Accuracy*\n"
    message += f"You: {user_data['overall_accuracy']:.1f}%\n"
    message += f"Average: {peer_averages['avg_accuracy']:.1f}%\n"
    message += f"Difference: {accuracy_diff:+.1f}%\n\n"

    # Compare questions answered
    questions_diff = user_data['total_questions'] - peer_averages['avg_questions']
    questions_emoji = "🟢" if questions_diff > 10 else "🟡" if questions_diff > -10 else "🔴"
    message += f"{questions_emoji} *Questions Answered*\n"
    message += f"You: {user_data['total_questions']}\n"
    message += f"Average: {peer_averages['avg_questions']:.0f}\n"
    message += f"Difference: {questions_diff:+.0f}\n\n"

    # Compare study streak
    streak_diff = user_data['study_streak'] - peer_averages['avg_streak']
    streak_emoji = "🟢" if streak_diff > 2 else "🟡" if streak_diff > -2 else "🔴"
    message += f"{streak_emoji} *Study Streak*\n"
    message += f"You: {user_data['study_streak']} days\n"
    message += f"Average: {peer_averages['avg_streak']:.1f} days\n"
    message += f"Difference: {streak_diff:+.1f} days\n\n"

    # Percentile ranking
    percentile = calculate_user_percentile(user_data, peer_averages)
    message += f"*📊 Your Ranking:* Top {100-percentile:.0f}% of learners\n\n"

    # Motivational message
    if percentile >= 75:
        message += "🌟 Outstanding performance! You're among the top learners!"
    elif percentile >= 50:
        message += "💪 Great job! You're performing above average!"
    else:
        message += "📚 Keep practicing! There's room for improvement!"

    keyboard = [
        [InlineKeyboardButton("🔙 Analytics Menu", callback_data="advanced_analytics")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def ai_tutoring_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start an interactive AI tutoring session"""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    quiz_session = context.user_data.get('quiz_session')
    if not quiz_session:
        quiz_session = load_user_stats(user.id)
        context.user_data['quiz_session'] = quiz_session

    learning_style = quiz_session.get_dominant_learning_style()
    weak_areas = [cat for cat, pattern in quiz_session.weakness_patterns.items() if pattern['error_count'] >= 2]

    message = (
        f"*🤖 AI Tutoring Hub*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Welcome {user.first_name}! Your AI tutor is ready to help.\n\n"
        f"*📊 Your Learning Profile:*\n"
        f"🎨 Learning Style: {learning_style.title()}\n"
        f"⭐ Current Level: {quiz_session.level}\n"
        f"📚 Focus Areas: {len(weak_areas)} topics\n"
        f"🔥 Study Streak: {quiz_session.daily_streak} days\n\n"
        "*🧠 Choose Your Learning Mode:*"
    )

    keyboard = [
        [InlineKeyboardButton("💬 Ask AI Tutor", callback_data="ai_chat"),
         InlineKeyboardButton("🎯 Concept Mapping", callback_data="concept_mapping")],
        [InlineKeyboardButton("📝 Step-by-Step Learning", callback_data="step_by_step"),
         InlineKeyboardButton("🤖 AI Practice Questions", callback_data="ai_practice")],
        [InlineKeyboardButton("🧭 Learning Path Guide", callback_data="learning_path"),
         InlineKeyboardButton("🔍 Weakness Analysis", callback_data="ai_weakness_help")],
        [InlineKeyboardButton("💡 Personalized Tips", callback_data="personalized_tips"),
         InlineKeyboardButton("🎨 Learning Style Test", callback_data="learning_style_test")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="start_menu")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def ai_weakness_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Provide AI help for weakness areas"""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    quiz_session = context.user_data.get('quiz_session')
    if not quiz_session:
        quiz_session = load_user_stats(user.id)
        context.user_data['quiz_session'] = quiz_session

    weak_areas = [cat for cat, pattern in quiz_session.weakness_patterns.items() if pattern['error_count'] >= 2]

    if weak_areas:
        message = (
            f"*🔍 AI Weakness Analysis for {user.first_name}*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "*Areas needing attention:*\n"
        )
        for area in weak_areas[:5]:
            error_count = quiz_session.weakness_patterns[area]['error_count']
            message += f"• {area} ({error_count} errors)\n"
        
        message += "\nSelect an area for personalized AI tutoring:"
        
        keyboard = []
        for area in weak_areas[:4]:
            keyboard.append([InlineKeyboardButton(f"📚 {area}", callback_data=f"ai_help_{area.replace(' ', '_')}")])
        
        keyboard.append([InlineKeyboardButton("🔙 Back to Tutoring", callback_data="ai_tutoring")])
    else:
        message = (
            "*🎉 Great job!*\n\n"
            "No significant weaknesses detected. You're performing well across all areas!\n\n"
            "Continue practicing to maintain your excellent performance."
        )
        keyboard = [[InlineKeyboardButton("🔙 Back to Tutoring", callback_data="ai_tutoring")]]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def learning_style_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Learning style assessment"""
    query = update.callback_query
    await query.answer()

    message = (
        "*🎨 Learning Style Assessment*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Answer these questions to optimize your learning experience:\n\n"
        "*Question 1: When studying anatomy, you prefer:*\n"
        "A) Looking at detailed diagrams and images\n"
        "B) Listening to explanations and discussions\n"
        "C) Using 3D models and hands-on practice\n"
        "D) Reading detailed textbooks and notes"
    )

    keyboard = [
        [InlineKeyboardButton("👁️ Visual (A)", callback_data="style_visual"),
         InlineKeyboardButton("🎵 Auditory (B)", callback_data="style_auditory")],
        [InlineKeyboardButton("✋ Kinesthetic (C)", callback_data="style_kinesthetic"),
         InlineKeyboardButton("📝 Reading/Writing (D)", callback_data="style_reading")],
        [InlineKeyboardButton("🔙 Back to Tutoring", callback_data="ai_tutoring")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_learning_style_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle learning style selection"""
    query = update.callback_query
    await query.answer()

    style_map = {
        "style_visual": "visual",
        "style_auditory": "auditory", 
        "style_kinesthetic": "kinesthetic",
        "style_reading": "reading_writing"
    }

    selected_style = style_map.get(query.data)
    
    user = update.effective_user
    quiz_session = context.user_data.get('quiz_session')
    if not quiz_session:
        quiz_session = load_user_stats(user.id)
        context.user_data['quiz_session'] = quiz_session

    # Update learning style preference
    quiz_session.learning_style[selected_style] = 100
    for style in quiz_session.learning_style:
        if style != selected_style:
            quiz_session.learning_style[style] = 0

    style_descriptions = {
        "visual": "You learn best through visual aids like diagrams, charts, and images. Use anatomical atlases and colorful study materials.",
        "auditory": "You learn best through listening and discussion. Try medical podcasts, group discussions, and verbal explanations.",
        "kinesthetic": "You learn best through hands-on practice and movement. Use physical models, lab work, and interactive simulations.",
        "reading_writing": "You learn best through reading and written work. Take detailed notes, create outlines, and use textbooks extensively."
    }

    message = (
        f"*🎨 Learning Style Updated: {selected_style.replace('_', '/').title()}*\n\n"
        f"{style_descriptions[selected_style]}\n\n"
        "*Your personalized recommendations:*\n"
        "• Explanations will be tailored to your learning style\n"
        "• Study suggestions will match your preferences\n"
        "• AI responses will be optimized for you\n\n"
        "Start asking questions to experience personalized learning!"
    )

    keyboard = [
        [InlineKeyboardButton("💬 Ask AI Question", callback_data="ai_chat")],
        [InlineKeyboardButton("🔙 Back to Tutoring", callback_data="ai_tutoring")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def sample_questions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show sample questions users can ask AI"""
    query = update.callback_query
    await query.answer()

    message = (
        "*📖 Sample AI Questions*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*🫀 Cardiovascular System:*\n"
        "• Explain the cardiac cycle in detail\n"
        "• What are the chambers of the heart?\n"
        "• How does blood pressure regulation work?\n\n"
        "*🧠 Nervous System:*\n"
        "• What are the 12 cranial nerves?\n"
        "• Explain action potential propagation\n"
        "• How does synaptic transmission work?\n\n"
        "*🫁 Respiratory System:*\n"
        "• Describe the mechanics of breathing\n"
        "• What is gas exchange in alveoli?\n"
        "• How is respiration controlled?\n\n"
        "*💀 Musculoskeletal System:*\n"
        "• Explain muscle contraction mechanism\n"
        "• What are the types of joints?\n"
        "• How does bone remodeling work?\n\n"
        "Just type your question and I'll provide detailed explanations!"
    )

    keyboard = [
        [InlineKeyboardButton("💬 Ask Your Question", callback_data="ai_chat")],
        [InlineKeyboardButton("🔙 Back to AI Chat", callback_data="ai_chat")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def quick_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show quick topic explanations"""
    query = update.callback_query
    await query.answer()

    message = (
        "*🎯 Quick Topic Explanations*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Select a topic for instant AI explanation:"
    )

    keyboard = [
        [InlineKeyboardButton("🫀 Heart Anatomy", callback_data="topic_heart"),
         InlineKeyboardButton("🧠 Brain Regions", callback_data="topic_brain")],
        [InlineKeyboardButton("🫁 Lung Function", callback_data="topic_lungs"),
         InlineKeyboardButton("💀 Bone Structure", callback_data="topic_bones")],
        [InlineKeyboardButton("🩸 Blood Components", callback_data="topic_blood"),
         InlineKeyboardButton("🧬 DNA Structure", callback_data="topic_dna")],
        [InlineKeyboardButton("🔙 Back to AI Chat", callback_data="ai_chat")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def study_techniques(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show study techniques"""
    query = update.callback_query
    await query.answer()

    message = (
        "*📚 Effective Study Techniques*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*🧠 Active Learning Methods:*\n"
        "• Spaced Repetition - Review at increasing intervals\n"
        "• Active Recall - Test yourself without looking\n"
        "• Interleaving - Mix different topics together\n"
        "• Elaborative Interrogation - Ask 'why' questions\n\n"
        "*📝 Note-Taking Strategies:*\n"
        "• Cornell Method - Divide notes into sections\n"
        "• Mind Mapping - Visual connections\n"
        "• Outline Method - Hierarchical structure\n"
        "• Charting - Tables for comparisons\n\n"
        "*🎯 Medical-Specific Tips:*\n"
        "• Use mnemonics for lists (e.g., cranial nerves)\n"
        "• Draw and label diagrams repeatedly\n"
        "• Practice with real cases\n"
        "• Form study groups for discussion"
    )

    keyboard = [
        [InlineKeyboardButton("⏰ Time Management", callback_data="time_management")],
        [InlineKeyboardButton("🔙 Back to Tips", callback_data="personalized_tips")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def time_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show time management tips"""
    query = update.callback_query
    await query.answer()

    message = (
        "*⏰ Time Management for Medical Students*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*📅 Study Schedule:*\n"
        "• Pomodoro Technique - 25min study, 5min break\n"
        "• Time blocking - Assign specific hours to subjects\n"
        "• Daily goals - Set achievable daily targets\n"
        "• Weekly reviews - Assess progress weekly\n\n"
        "*⚡ Efficiency Tips:*\n"
        "• Study during peak energy hours\n"
        "• Eliminate distractions (phone, social media)\n"
        "• Use active learning techniques\n"
        "• Take regular breaks to maintain focus\n\n"
        "*🎯 Priority Management:*\n"
        "• High-yield topics first\n"
        "• Weak areas need more time\n"
        "• Balance breadth vs depth\n"
        "• Regular practice testing"
    )

    keyboard = [
        [InlineKeyboardButton("🧠 Memory Strategies", callback_data="memory_strategies")],
        [InlineKeyboardButton("🔙 Back to Tips", callback_data="personalized_tips")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def memory_strategies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show memory strategies"""
    query = update.callback_query
    await query.answer()

    message = (
        "*🧠 Memory Enhancement Strategies*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*🔤 Mnemonics for Medical Terms:*\n"
        "• Cranial Nerves: 'On Old Olympus...'\n"
        "• Carpal Bones: 'Some Lovers Try Positions...'\n"
        "• Amino Acids: Create acronyms\n"
        "• Drug Classifications: Group by mechanism\n\n"
        "*🧩 Memory Palace Technique:*\n"
        "• Associate information with familiar locations\n"
        "• Create vivid, unusual mental images\n"
        "• Follow a consistent route through your 'palace'\n"
        "• Practice regularly to strengthen associations\n\n"
        "*🔗 Association Methods:*\n"
        "• Link new info to known concepts\n"
        "• Use visual imagery\n"
        "• Create stories or narratives\n"
        "• Use rhymes and rhythms\n\n"
        "*📊 Spaced Repetition:*\n"
        "• Review immediately after learning\n"
        "• Review again after 1 day\n"
        "• Then after 3 days, 1 week, 2 weeks\n"
        "• Adjust intervals based on difficulty"
    )

    keyboard = [
        [InlineKeyboardButton("📝 Note Taking", callback_data="note_taking")],
        [InlineKeyboardButton("🔙 Back to Tips", callback_data="personalized_tips")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def note_taking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show note-taking strategies"""
    query = update.callback_query
    await query.answer()

    message = (
        "*📝 Effective Note-Taking for Medicine*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*📋 Cornell Method:*\n"
        "• Divide page: notes, cues, summary\n"
        "• Take notes in main section\n"
        "• Add keywords/questions in cue column\n"
        "• Summarize at bottom\n\n"
        "*🗺️ Mind Mapping:*\n"
        "• Central topic in center\n"
        "• Branch out to subtopics\n"
        "• Use colors and symbols\n"
        "• Great for anatomy connections\n\n"
        "*📊 Medical-Specific Formats:*\n"
        "• System-based organization\n"
        "• Clinical correlation notes\n"
        "• Diagram annotations\n"
        "• Case study summaries\n\n"
        "*💡 Digital vs Paper:*\n"
        "• Digital: searchable, multimedia\n"
        "• Paper: better retention, drawings\n"
        "• Hybrid approach often best\n"
        "• Sync across devices for access"
    )

    keyboard = [
        [InlineKeyboardButton("📚 Study Techniques", callback_data="study_techniques")],
        [InlineKeyboardButton("🔙 Back to Tips", callback_data="personalized_tips")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def create_study_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help create personalized study plan"""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    quiz_session = context.user_data.get('quiz_session')
    if not quiz_session:
        quiz_session = load_user_stats(user.id)
        context.user_data['quiz_session'] = quiz_session

    weak_areas = [cat for cat, pattern in quiz_session.weakness_patterns.items() if pattern['error_count'] >= 2]
    level = quiz_session.level

    message = (
        f"*📋 Personalized Study Plan for {user.first_name}*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"*📊 Current Level:* {level}\n"
        f"*🎯 Focus Areas:* {len(weak_areas)} topics need attention\n\n"
        "*📅 Recommended Weekly Schedule:*\n"
        "• Monday: Anatomy review (2 hours)\n"
        "• Tuesday: Physiology concepts (2 hours)\n"
        "• Wednesday: Practice questions (1.5 hours)\n"
        "• Thursday: Weak areas focus (2 hours)\n"
        "• Friday: Integration & review (1.5 hours)\n"
        "• Weekend: Practice tests & revision\n\n"
    )

    if weak_areas:
        message += "*🔍 Priority Topics for You:*\n"
        for area in weak_areas[:3]:
            message += f"• {area}\n"
        message += "\n"

    message += (
        "*🎯 Daily Goals:*\n"
        "• 20-30 quiz questions\n"
        "• 1 new concept mastery\n"
        "• Review previous mistakes\n"
        "• 15 minutes of active recall"
    )

    keyboard = [
        [InlineKeyboardButton("🎯 Set Goals", callback_data="set_goals")],
        [InlineKeyboardButton("🔙 Back to Learning Path", callback_data="learning_path")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def set_goals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help set learning goals"""
    query = update.callback_query
    await query.answer()

    message = (
        "*🎯 Set Your Learning Goals*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*🏆 Goal Categories:*\n\n"
        "*📊 Performance Goals:*\n"
        "• Achieve 90% accuracy in anatomy\n"
        "• Complete 100 questions this week\n"
        "• Master 5 new concepts daily\n"
        "• Maintain 7-day study streak\n\n"
        "*📚 Knowledge Goals:*\n"
        "• Complete cardiovascular system\n"
        "• Master all cranial nerves\n"
        "• Understand muscle physiology\n"
        "• Learn drug mechanisms\n\n"
        "*⏰ Time Goals:*\n"
        "• Study 2 hours daily\n"
        "• Complete morning review\n"
        "• Finish weekly practice test\n"
        "• Review notes before sleep\n\n"
        "*💡 SMART Goals Framework:*\n"
        "• Specific - Clear and defined\n"
        "• Measurable - Track progress\n"
        "• Achievable - Realistic targets\n"
        "• Relevant - Match your needs\n"
        "• Time-bound - Set deadlines"
    )

    keyboard = [
        [InlineKeyboardButton("📊 Track Progress", callback_data="track_progress")],
        [InlineKeyboardButton("🔙 Back to Learning Path", callback_data="learning_path")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def track_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show progress tracking tools"""
    query = update.callback_query
    await query.answer()

    message = (
        "*📊 Progress Tracking Tools*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*📈 Available Analytics:*\n"
        "• Daily performance trends\n"
        "• Topic mastery levels\n"
        "• Learning curve analysis\n"
        "• Weakness identification\n"
        "• Time investment tracking\n"
        "• Peer comparison data\n\n"
        "*🎯 Progress Indicators:*\n"
        "• Quiz accuracy percentages\n"
        "• Study streak counters\n"
        "• XP and level progression\n"
        "• Badge achievements\n"
        "• Concept mastery scores\n\n"
        "*📅 Regular Reviews:*\n"
        "• Weekly progress summaries\n"
        "• Monthly goal assessments\n"
        "• Quarterly learning evaluations\n"
        "• Continuous improvement plans"
    )

    keyboard = [
        [InlineKeyboardButton("📈 View Analytics", callback_data="advanced_analytics")],
        [InlineKeyboardButton("📊 My Progress", callback_data="show_stats")],
        [InlineKeyboardButton("🔙 Back to Learning Path", callback_data="learning_path")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_step_tutorials(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle step-by-step tutorials"""
    query = update.callback_query
    await query.answer()

    system = query.data.replace("step_", "")
    
    processing_message = await query.edit_message_text(
        f"🧠 *Generating step-by-step tutorial for {system}...*",
        parse_mode="Markdown"
    )

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "deepseek/deepseek-v3-base:free",
                "messages": [
                    {"role": "system", "content": "Provide a detailed step-by-step explanation of the topic. Break down complex concepts into digestible steps with clear numbering."},
                    {"role": "user", "content": f"Create a step-by-step tutorial for {system} system in anatomy and physiology"}
                ]
            }
        )

        data = response.json()
        if "choices" in data and len(data["choices"]) > 0:
            tutorial = data["choices"][0]["message"]["content"]
            
            final_message = (
                f"*📝 Step-by-Step: {system.title()} System*\n"
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{tutorial}"
            )

            keyboard = [
                [InlineKeyboardButton("🎯 Quiz This Topic", callback_data=f"category_{system}")],
                [InlineKeyboardButton("🔄 Another Tutorial", callback_data="step_by_step")],
                [InlineKeyboardButton("🔙 Back to Tutoring", callback_data="ai_tutoring")]
            ]

            await processing_message.edit_text(
                final_message,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await processing_message.edit_text(
                "Sorry, I couldn't generate the tutorial. Please try again.",
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error generating tutorial: {str(e)}")
        await processing_message.edit_text(
            "Error generating tutorial. Please try again later.",
            parse_mode="Markdown"
        )

async def handle_ai_practice_generation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle AI practice question generation"""
    query = update.callback_query
    await query.answer()

    topic = query.data.replace("gen_", "")
    
    processing_message = await query.edit_message_text(
        f"🤖 *Generating practice questions for {topic}...*",
        parse_mode="Markdown"
    )

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "deepseek/deepseek-v3-base:free",
                "messages": [
                    {"role": "system", "content": "Generate 5 medical practice questions in True/False format. For each question, provide the question, answer (True/False), and a detailed explanation."},
                    {"role": "user", "content": f"Create practice questions about {topic} in medical education"}
                ]
            }
        )

        data = response.json()
        if "choices" in data and len(data["choices"]) > 0:
            questions = data["choices"][0]["message"]["content"]
            
            final_message = (
                f"*🤖 AI-Generated Practice Questions: {topic.title()}*\n"
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{questions}"
            )

            keyboard = [
                [InlineKeyboardButton("🎯 Take Regular Quiz", callback_data="main_categories")],
                [InlineKeyboardButton("🔄 Generate More", callback_data="ai_practice")],
                [InlineKeyboardButton("🔙 Back to Tutoring", callback_data="ai_tutoring")]
            ]

            await processing_message.edit_text(
                final_message,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await processing_message.edit_text(
                "Sorry, I couldn't generate questions. Please try again.",
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error generating questions: {str(e)}")
        await processing_message.edit_text(
            "Error generating questions. Please try again later.",
            parse_mode="Markdown"
        )

async def handle_ai_help_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle AI help for specific topics"""
    query = update.callback_query
    await query.answer()

    topic = query.data.replace("ai_help_", "").replace("_", " ")
    
    processing_message = await query.edit_message_text(
        f"🧠 *Getting AI help for {topic}...*",
        parse_mode="Markdown"
    )

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "deepseek/deepseek-v3-base:free",
                "messages": [
                    {"role": "system", "content": "Provide comprehensive help and study strategies for the medical topic. Include key concepts, common mistakes, and learning tips."},
                    {"role": "user", "content": f"Provide detailed help and study guidance for {topic} in medical education"}
                ]
            }
        )

        data = response.json()
        if "choices" in data and len(data["choices"]) > 0:
            help_content = data["choices"][0]["message"]["content"]
            
            final_message = (
                f"*🧠 AI Help: {topic.title()}*\n"
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{help_content}"
            )

            keyboard = [
                [InlineKeyboardButton("🎯 Practice This Topic", callback_data=f"category_{topic}")],
                [InlineKeyboardButton("🔄 Get More Help", callback_data="ai_weakness_help")],
                [InlineKeyboardButton("🔙 Back to Tutoring", callback_data="ai_tutoring")]
            ]

            await processing_message.edit_text(
                final_message,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await processing_message.edit_text(
                "Sorry, I couldn't provide help. Please try again.",
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error getting AI help: {str(e)}")
        await processing_message.edit_text(
            "Error getting help. Please try again later.",
            parse_mode="Markdown"
        )

async def ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Interactive AI chat interface"""
    query = update.callback_query
    await query.answer()

    message = (
        "*💬 AI Chat Tutor*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Ask me anything about medical topics! I'm here to help with:\n\n"
        "🧠 *Complex Concepts*\n"
        "📚 *Study Strategies*\n"
        "🔬 *Clinical Applications*\n"
        "📝 *Exam Preparation*\n"
        "🎯 *Topic Explanations*\n\n"
        "*Just type your question and I'll provide personalized guidance!*\n\n"
        "*Example Questions:*\n"
        "• Explain the cardiac cycle\n"
        "• What are the cranial nerves?\n"
        "• How does muscle contraction work?\n"
        "• Create a study plan for anatomy"
    )

    keyboard = [
        [InlineKeyboardButton("📖 Sample Questions", callback_data="sample_questions"),
         InlineKeyboardButton("🎯 Quick Topics", callback_data="quick_topics")],
        [InlineKeyboardButton("🔙 Back to Tutoring", callback_data="ai_tutoring")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def step_by_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Provide step-by-step learning guidance"""
    query = update.callback_query
    await query.answer()

    message = (
        "*📝 Step-by-Step Learning*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Choose a topic for detailed, step-by-step explanation:\n\n"
        "*🫀 Cardiovascular System*\n"
        "• Heart anatomy and function\n"
        "• Blood circulation pathways\n"
        "• Cardiac cycle phases\n\n"
        "*🧠 Nervous System*\n"
        "• Neuron structure and function\n"
        "• Action potential mechanism\n"
        "• Synaptic transmission\n\n"
        "*🫁 Respiratory System*\n"
        "• Breathing mechanics\n"
        "• Gas exchange process\n"
        "• Respiratory control"
    )

    keyboard = [
        [InlineKeyboardButton("🫀 Cardiovascular", callback_data="step_cardiovascular"),
         InlineKeyboardButton("🧠 Nervous System", callback_data="step_nervous")],
        [InlineKeyboardButton("🫁 Respiratory", callback_data="step_respiratory"),
         InlineKeyboardButton("💀 Musculoskeletal", callback_data="step_musculo")],
        [InlineKeyboardButton("🔙 Back to Tutoring", callback_data="ai_tutoring")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def ai_practice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate AI practice questions"""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    quiz_session = context.user_data.get('quiz_session')
    if not quiz_session:
        quiz_session = load_user_stats(user.id)
        context.user_data['quiz_session'] = quiz_session

    weak_areas = [cat for cat, pattern in quiz_session.weakness_patterns.items() if pattern['error_count'] >= 2]

    message = (
        "*🤖 AI Practice Questions*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "I'll generate personalized practice questions based on your needs!\n\n"
    )

    if weak_areas:
        message += f"*🎯 Recommended Focus Areas:*\n"
        for area in weak_areas[:3]:
            message += f"• {area}\n"
        message += "\n"

    message += (
        "*Choose a topic for AI-generated questions:*\n\n"
        "🧠 Questions will adapt to your learning style\n"
        "📊 Difficulty adjusts based on your performance\n"
        "💡 Detailed explanations included"
    )

    keyboard = [
        [InlineKeyboardButton("🦴 Anatomy Questions", callback_data="gen_anatomy"),
         InlineKeyboardButton("🧬 Physiology Questions", callback_data="gen_physiology")],
        [InlineKeyboardButton("🫀 Cardiovascular", callback_data="gen_cardio"),
         InlineKeyboardButton("🧠 Neurology", callback_data="gen_neuro")],
        [InlineKeyboardButton("🎯 My Weak Areas", callback_data="gen_weakness"),
         InlineKeyboardButton("🎲 Random Mix", callback_data="gen_random")],
        [InlineKeyboardButton("🔙 Back to Tutoring", callback_data="ai_tutoring")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def learning_path(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Provide personalized learning path guidance"""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    quiz_session = context.user_data.get('quiz_session')
    if not quiz_session:
        quiz_session = load_user_stats(user.id)
        context.user_data['quiz_session'] = quiz_session

    accuracy = quiz_session.get_accuracy()
    level = quiz_session.level

    if level <= 5:
        stage = "Beginner"
        recommendations = [
            "Focus on basic anatomy terminology",
            "Learn fundamental physiological processes",
            "Practice with visual aids and diagrams"
        ]
    elif level <= 15:
        stage = "Intermediate"
        recommendations = [
            "Integrate anatomy with physiology",
            "Study clinical correlations",
            "Practice with case-based questions"
        ]
    else:
        stage = "Advanced"
        recommendations = [
            "Master complex pathophysiology",
            "Focus on clinical applications",
            "Prepare for professional exams"
        ]

    message = (
        f"*🧭 Personalized Learning Path*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"*📊 Current Status:*\n"
        f"🎯 Level: {level} ({stage})\n"
        f"📈 Accuracy: {accuracy:.1f}%\n"
        f"🔥 Streak: {quiz_session.daily_streak} days\n\n"
        f"*🎯 Recommended Learning Path:*\n"
    )

    for i, rec in enumerate(recommendations, 1):
        message += f"{i}. {rec}\n"

    message += (
        f"\n*📚 Next Steps:*\n"
        "• Complete daily practice sessions\n"
        "• Focus on weak areas identified\n"
        "• Use spaced repetition for retention\n"
        "• Join study groups for discussion"
    )

    keyboard = [
        [InlineKeyboardButton("📋 Create Study Plan", callback_data="create_study_plan"),
         InlineKeyboardButton("🎯 Set Goals", callback_data="set_goals")],
        [InlineKeyboardButton("📊 Track Progress", callback_data="track_progress"),
         InlineKeyboardButton("🏆 View Achievements", callback_data="view_badges")],
        [InlineKeyboardButton("🔙 Back to Tutoring", callback_data="ai_tutoring")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def personalized_tips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Provide personalized study tips"""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    quiz_session = context.user_data.get('quiz_session')
    if not quiz_session:
        quiz_session = load_user_stats(user.id)
        context.user_data['quiz_session'] = quiz_session

    learning_style = quiz_session.get_dominant_learning_style()
    accuracy = quiz_session.get_accuracy()

    style_tips = {
        'visual': [
            "Use anatomical diagrams and charts",
            "Create colorful mind maps",
            "Watch educational videos",
            "Use flashcards with images"
        ],
        'auditory': [
            "Listen to medical podcasts",
            "Study with background music",
            "Join study groups for discussion",
            "Record yourself explaining concepts"
        ],
        'kinesthetic': [
            "Use hands-on models and simulations",
            "Practice with physical examination",
            "Take breaks and move around",
            "Use gesture-based memory techniques"
        ],
        'reading_writing': [
            "Take detailed notes",
            "Create comprehensive outlines",
            "Write summaries after studying",
            "Use text-based learning materials"
        ]
    }

    message = (
        f"*💡 Personalized Study Tips*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"*🎨 Your Learning Style: {learning_style.title()}*\n\n"
        f"*📚 Recommended Study Methods:*\n"
    )

    tips = style_tips.get(learning_style, style_tips['reading_writing'])
    for i, tip in enumerate(tips, 1):
        message += f"{i}. {tip}\n"

    if accuracy < 60:
        message += (
            f"\n*🎯 Based on your {accuracy:.1f}% accuracy:*\n"
            "• Focus on understanding rather than memorization\n"
            "• Review incorrect answers thoroughly\n"
            "• Practice with easier questions first\n"
            "• Use active recall techniques"
        )
    elif accuracy < 80:
        message += (
            f"\n*📈 To improve from {accuracy:.1f}%:*\n"
            "• Practice spaced repetition\n"
            "• Focus on challenging topics\n"
            "• Create connections between concepts\n"
            "• Test yourself regularly"
        )
    else:
        message += (
            f"\n*🌟 Excellent {accuracy:.1f}% accuracy! Maintain by:*\n"
            "• Teaching others\n"
            "• Exploring advanced topics\n"
            "• Taking practice exams\n"
            "• Reviewing periodically"
        )

    keyboard = [
        [InlineKeyboardButton("📖 Study Techniques", callback_data="study_techniques"),
         InlineKeyboardButton("⏰ Time Management", callback_data="time_management")],
        [InlineKeyboardButton("🧠 Memory Strategies", callback_data="memory_strategies"),
         InlineKeyboardButton("📝 Note Taking", callback_data="note_taking")],
        [InlineKeyboardButton("🔙 Back to Tutoring", callback_data="ai_tutoring")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def concept_mapping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate concept maps for better understanding"""
    query = update.callback_query
    await query.answer()

    message = (
        "*🗺️ Concept Mapping*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Select a topic to generate an interactive concept map showing relationships between medical concepts:"
    )

    keyboard = [
        [InlineKeyboardButton("🫀 Cardiovascular System", callback_data="map_cardiovascular"),
         InlineKeyboardButton("🧠 Nervous System", callback_data="map_nervous")],
        [InlineKeyboardButton("🫁 Respiratory System", callback_data="map_respiratory"),
         InlineKeyboardButton("💀 Skeletal System", callback_data="map_skeletal")],
        [InlineKeyboardButton("🔙 Back to Tutoring", callback_data="ai_tutoring")]
    ]

    await query.edit_message_text(
        message,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def generate_concept_map(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate AI-powered concept map"""
    query = update.callback_query
    await query.answer()

    system_name = query.data.replace("map_", "")
    
    processing_message = await query.edit_message_text(
        "🧠 *Generating concept map...*\nMapping relationships and connections...",
        parse_mode="Markdown"
    )

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "deepseek/deepseek-v3-base:free",
                "messages": [
                    {"role": "system", "content": "Create a detailed concept map showing relationships between anatomical structures and physiological processes. Use arrows (→) and connections (↔) to show relationships."},
                    {"role": "user", "content": f"Create a concept map for the {system_name} system showing key structures, functions, and their relationships"}
                ]
            }
        )

        data = response.json()
        if "choices" in data and len(data["choices"]) > 0:
            concept_map = data["choices"][0]["message"]["content"]
            
            final_message = (
                f"*🗺️ {system_name.title()} System Concept Map*\n"
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{concept_map}\n\n"
                "*💡 Study Tip:* Use this map to understand how different components work together!"
            )

            keyboard = [
                [InlineKeyboardButton("🎯 Quiz This Topic", callback_data=f"category_{system_name}")],
                [InlineKeyboardButton("🔄 Generate Another Map", callback_data="concept_mapping")],
                [InlineKeyboardButton("🔙 Back to Tutoring", callback_data="ai_tutoring")]
            ]

            await processing_message.edit_text(
                final_message,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await processing_message.edit_text(
                "Sorry, I couldn't generate the concept map. Please try again.",
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error generating concept map: {str(e)}")
        await processing_message.edit_text(
            "Error generating concept map. Please try again later.",
            parse_mode="Markdown"
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
            "Your AI-powered medical learning companion!\n\n"
            "🎯*ENHANCED AI FEATURES*\n"
            "🤖 Personalized AI Tutoring\n"
            "🗺️ Concept Mapping & Visualization\n"
            "📚 AI-Generated Practice Questions\n"
            "💡 Adaptive Learning Explanations\n"
            "🧠 Intelligent Step-by-Step Guidance\n\n"
            "⚡️ *QUICK COMMANDS*\n"
            "📋 /stats - Your Performance\n"
            "🗂 /categories - Browse Topics\n"
            "❓ /help - Get Assistance\n"
            "💬 /ask - Enhanced AI Questions\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "*Ready to experience AI-powered learning?*"
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
                InlineKeyboardButton("🤖 AI Tutoring", callback_data="ai_tutoring"),
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

async def generate_personalized_explanation(question_content, user_learning_style, is_correct):
    """Generate personalized explanations based on learning style"""
    try:
        # Customize prompt based on learning style
        style_prompts = {
            'visual': "Provide a visual explanation with diagrams, anatomical landmarks, and spatial relationships. Use descriptive imagery.",
            'auditory': "Explain with verbal mnemonics, pronunciation guides, and auditory associations. Include rhythm and sound-based memory aids.",
            'kinesthetic': "Focus on hands-on understanding, movement, touch sensations, and practical applications. Include physical examination techniques.",
            'reading_writing': "Provide detailed written explanations with lists, definitions, and step-by-step processes. Include note-taking strategies."
        }
        
        correction_context = "The user answered incorrectly, so focus on clarifying misconceptions and reinforcing the correct concept." if not is_correct else "The user answered correctly, so provide reinforcing details and advanced insights."
        
        style_instruction = style_prompts.get(user_learning_style, style_prompts['reading_writing'])
        
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "deepseek/deepseek-v3-base:free",
                "messages": [
                    {"role": "system", "content": f"You are an expert medical educator. {style_instruction} {correction_context}"},
                    {"role": "user", "content": f"Explain this medical concept: {question_content}"}
                ]
            }
        )
        
        data = response.json()
        if "choices" in data and len(data["choices"]) > 0:
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Error generating personalized explanation: {str(e)}")
    
    return None

async def generate_ai_practice_questions(topic, difficulty_level, user_weaknesses):
    """Generate AI practice questions based on user's learning needs"""
    try:
        weakness_context = f"Focus on these specific areas where the user struggles: {', '.join(user_weaknesses)}" if user_weaknesses else ""
        
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "deepseek/deepseek-v3-base:free",
                "messages": [
                    {"role": "system", "content": f"Generate 3 True/False medical questions about {topic} at {difficulty_level} difficulty level. {weakness_context} Format each as: Question|True/False|Explanation"},
                    {"role": "user", "content": f"Create practice questions for {topic}"}
                ]
            }
        )
        
        data = response.json()
        if "choices" in data and len(data["choices"]) > 0:
            questions_text = data["choices"][0]["message"]["content"]
            # Parse the generated questions
            questions = []
            for line in questions_text.split('\n'):
                if '|' in line:
                    parts = line.split('|')
                    if len(parts) >= 3:
                        questions.append({
                            'question': parts[0].strip(),
                            'answer': parts[1].strip().lower() == 'true',
                            'explanation': parts[2].strip(),
                            'generated': True
                        })
            return questions
    except Exception as e:
        logger.error(f"Error generating AI questions: {str(e)}")
    
    return []

async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process user questions with enhanced AI features."""
    if not context.args:
        await update.message.reply_text(
            "*🧠 Enhanced AI Medical Tutor*\n\n"
            "Use /ask followed by your medical question.\n\n"
            "*Examples:*\n"
            "/ask What are the branches of the facial nerve?\n"
            "/ask Explain the cardiac cycle\n"
            "/ask Generate practice questions on anatomy\n\n"
            "*New AI Features:*\n"
            "• Personalized explanations based on your learning style\n"
            "• Step-by-step tutoring guidance\n"
            "• Concept relationship mapping\n"
            "• AI-generated practice questions",
            parse_mode="Markdown"
        )
        return

    question = " ".join(context.args)
    user = update.effective_user
    
    # Get user's learning preferences
    quiz_session = context.user_data.get('quiz_session')
    if not quiz_session:
        quiz_session = load_user_stats(user.id)
        context.user_data['quiz_session'] = quiz_session
    
    learning_style = quiz_session.get_dominant_learning_style()

    # Let user know we're processing
    processing_message = await update.message.reply_text(
        "🧠 *Enhanced AI Processing...*\n"
        f"Adapting response for {learning_style} learning style...",
        parse_mode="Markdown"
    )

    try:
        # Check if user wants practice questions
        if "generate" in question.lower() and "question" in question.lower():
            topic = question.replace("generate", "").replace("practice", "").replace("questions", "").replace("on", "").strip()
            user_weaknesses = [cat for cat, pattern in quiz_session.weakness_patterns.items() if pattern['error_count'] >= 3]
            
            ai_questions = await generate_ai_practice_questions(topic, "intermediate", user_weaknesses)
            
            if ai_questions:
                response_text = f"*🤖 AI-Generated Practice Questions: {topic}*\n\n"
                for i, q in enumerate(ai_questions, 1):
                    response_text += f"*Question {i}:*\n{q['question']}\n\n"
                    response_text += f"*Answer:* {'True' if q['answer'] else 'False'}\n"
                    response_text += f"*Explanation:* {q['explanation']}\n\n"
                    response_text += "━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                await processing_message.edit_text(response_text, parse_mode="Markdown")
                return
        
        # Enhanced system prompt based on learning style
        style_instructions = {
            'visual': "Use visual descriptions, spatial relationships, and imagery. Include anatomical landmarks and visual mnemonics.",
            'auditory': "Use verbal explanations, pronunciation guides, and auditory mnemonics. Include rhythmic patterns and sound associations.",
            'kinesthetic': "Focus on hands-on understanding, physical examination techniques, and practical applications. Include movement and touch sensations.",
            'reading_writing': "Provide detailed written explanations with lists, step-by-step processes, and comprehensive definitions."
        }
        
        enhanced_prompt = f"You are an expert medical tutor specializing in anatomy and physiology. {style_instructions.get(learning_style, style_instructions['reading_writing'])} Provide step-by-step guidance when explaining complex concepts."

        # Call the OpenRouter API with enhanced prompting
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://replit.com",
                "X-Title": "Medical Education Bot"
            },
            json={
                "model": "deepseek/deepseek-v3-base:free",
                "messages": [
                    {"role": "system", "content": enhanced_prompt},
                    {"role": "user", "content": question}
                ],
                "max_tokens": 1000,
                "temperature": 0.7
            },
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            
            if "choices" in data and len(data["choices"]) > 0:
                answer = data["choices"][0]["message"]["content"]
                
                # Add learning style indicator
                style_emoji = {
                    'visual': '👁️', 'auditory': '🎵', 
                    'kinesthetic': '✋', 'reading_writing': '📝', 'balanced': '⚖️'
                }
                
                final_answer = f"*{style_emoji.get(learning_style, '🧠')} Personalized for {learning_style.title()} Learning*\n\n{answer}"

                # Send answer in chunks if needed
                if len(final_answer) > 4000:
                    chunks = [final_answer[i:i+4000] for i in range(0, len(final_answer), 4000)]
                    await processing_message.delete()

                    for i, chunk in enumerate(chunks):
                        if i == 0:
                            await update.message.reply_text(
                                f"*🧠 Enhanced AI Answer*\n\n{chunk}",
                                parse_mode="Markdown"
                            )
                        else:
                            await update.message.reply_text(chunk, parse_mode="Markdown")
                else:
                    await processing_message.edit_text(final_answer, parse_mode="Markdown")
            else:
                await processing_message.edit_text(
                    "I received an empty response. Please try rephrasing your question.",
                    parse_mode="Markdown"
                )
        else:
            logger.error(f"API Error: Status {response.status_code}, Response: {response.text}")
            await processing_message.edit_text(
                f"API Error (Status {response.status_code}). Please try again in a moment.",
                parse_mode="Markdown"
            )
            
    except requests.exceptions.Timeout:
        logger.error("API request timed out")
        await processing_message.edit_text(
            "Request timed out. Please try again with a shorter question.",
            parse_mode="Markdown"
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error in ask_command: {str(e)}")
        await processing_message.edit_text(
            "Network error occurred. Please check your connection and try again.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in enhanced ask_command: {str(e)}")
        await processing_message.edit_text(
            "An unexpected error occurred. Please try again later.",
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

    # Create application with error handling
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Add error handler for conflicts
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log the error and send a telegram message to notify the developer."""
        logger.error("Exception while handling an update:", exc_info=context.error)
        
        # Handle specific error types
        if "Conflict" in str(context.error):
            logger.warning("Bot conflict detected. Waiting before retry...")
            await asyncio.sleep(5)
        elif "terminated by other getUpdates request" in str(context.error):
            logger.warning("Multiple bot instances detected. This instance will continue after brief pause...")
            await asyncio.sleep(10)
    
    application.add_error_handler(error_handler)

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
    application.add_handler(CallbackQueryHandler(view_badges, pattern="^view_badges$"))
    application.add_handler(CallbackQueryHandler(spaced_review, pattern="^spaced_review$"))
    application.add_handler(CallbackQueryHandler(start_review_session, pattern="^start_review_session$"))
    application.add_handler(CallbackQueryHandler(advanced_analytics, pattern="^advanced_analytics$"))
    application.add_handler(CallbackQueryHandler(learning_curve_analysis, pattern="^learning_curve$"))
    application.add_handler(CallbackQueryHandler(time_analysis, pattern="^time_analysis$"))
    application.add_handler(CallbackQueryHandler(weakness_analysis, pattern="^weakness_analysis$"))
    application.add_handler(CallbackQueryHandler(peer_comparison, pattern="^peer_comparison$"))
    application.add_handler(CallbackQueryHandler(concept_mastery_analysis, pattern="^concept_mastery$"))
    application.add_handler(CallbackQueryHandler(performance_trends, pattern="^performance_trends$"))
    application.add_handler(CallbackQueryHandler(ai_tutoring_session, pattern="^ai_tutoring$"))
    application.add_handler(CallbackQueryHandler(ai_chat, pattern="^ai_chat$"))
    application.add_handler(CallbackQueryHandler(step_by_step, pattern="^step_by_step$"))
    application.add_handler(CallbackQueryHandler(ai_practice, pattern="^ai_practice$"))
    application.add_handler(CallbackQueryHandler(learning_path, pattern="^learning_path$"))
    application.add_handler(CallbackQueryHandler(personalized_tips, pattern="^personalized_tips$"))
    application.add_handler(CallbackQueryHandler(concept_mapping, pattern="^concept_mapping$"))
    application.add_handler(CallbackQueryHandler(generate_concept_map, pattern="^map_"))
    application.add_handler(CallbackQueryHandler(ai_weakness_help, pattern="^ai_weakness_help$"))
    application.add_handler(CallbackQueryHandler(learning_style_test, pattern="^learning_style_test$"))
    application.add_handler(CallbackQueryHandler(handle_learning_style_selection, pattern="^style_"))
    
    # Add missing AI tutoring handlers
    application.add_handler(CallbackQueryHandler(sample_questions, pattern="^sample_questions$"))
    application.add_handler(CallbackQueryHandler(quick_topics, pattern="^quick_topics$"))
    application.add_handler(CallbackQueryHandler(study_techniques, pattern="^study_techniques$"))
    application.add_handler(CallbackQueryHandler(time_management, pattern="^time_management$"))
    application.add_handler(CallbackQueryHandler(memory_strategies, pattern="^memory_strategies$"))
    application.add_handler(CallbackQueryHandler(note_taking, pattern="^note_taking$"))
    application.add_handler(CallbackQueryHandler(create_study_plan, pattern="^create_study_plan$"))
    application.add_handler(CallbackQueryHandler(set_goals, pattern="^set_goals$"))
    application.add_handler(CallbackQueryHandler(track_progress, pattern="^track_progress$"))
    application.add_handler(CallbackQueryHandler(handle_step_tutorials, pattern="^step_"))
    application.add_handler(CallbackQueryHandler(handle_ai_practice_generation, pattern="^gen_"))
    application.add_handler(CallbackQueryHandler(handle_ai_help_topic, pattern="^ai_help_"))

    # Start the Bot with improved error handling
    try:
        logger.info("Starting bot...")
        application.run_polling(
            poll_interval=2.0,  # Increase polling interval to reduce conflicts
            timeout=20,         # Increase timeout
            bootstrap_retries=5 # Add retry logic for bootstrap
        )
    except Exception as e:
        logger.error(f"Failed to start bot: {str(e)}")
        if "Conflict" in str(e):
            logger.info("Conflict detected. Waiting 10 seconds before restart...")
            time.sleep(10)
            logger.info("Attempting to restart bot...")
            application.run_polling(
                poll_interval=3.0,
                timeout=30,
                bootstrap_retries=3
            )

if __name__ == "__main__":
    main()
