import re
import unicodedata
from socketio import socketio_manage
from socketio.namespace import BaseNamespace
from socketio.mixins import RoomsMixin, BroadcastMixin
from werkzeug.exceptions import NotFound
from gevent import monkey

from flask import Flask, Response, request, render_template, url_for, redirect
from flask.ext.sqlalchemy import SQLAlchemy

monkey.patch_all()

app = Flask(__name__)
app.debug = True
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/chat.db'
db = SQLAlchemy(app)


# models
class ChatRoom(db.Model):
    __tablename__ = 'chatrooms'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(20), nullable=False)
    slug = db.Column(db.String(50))
    users = db.relationship('ChatUser', backref='chatroom', lazy='dynamic')

    def __unicode__(self):
        return self.name

    def get_absolute_url(self):
        return url_for('room', slug=self.slug)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        db.session.add(self)
        db.session.commit()


class ChatUser(db.Model):
    __tablename__ = 'chatusers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(20), nullable=False)
    session = db.Column(db.String(20), nullable=False)
    chatroom_id = db.Column(db.Integer, db.ForeignKey('chatrooms.id'))

    def __unicode__(self):
        return self.name


# utils
def slugify(value):
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore')
    value = unicode(re.sub('[^\w\s-]', '', value).strip().lower())
    return re.sub('[-\s]+', '-', value)


def get_object_or_404(klass, **query):
    instance = klass.query.filter_by(**query).first()
    if not instance:
        raise NotFound()
    return instance


def get_or_create(klass, **kwargs):
    try:
        return get_object_or_404(klass, **kwargs), False
    except NotFound:
        instance = klass(**kwargs)
        instance.save()
        return instance, True


def init_db():
    db.create_all(app=app)


# views
@app.route('/')
def rooms():
    """
    Homepage - lists all rooms.
    """
    context = {"rooms": ChatRoom.query.all()}
    return render_template('rooms.html', **context)


@app.route('/<path:slug>')
def room(slug):
    """
    Show a room.
    """
    context = {"room": get_object_or_404(ChatRoom, slug=slug)}
    return render_template('room.html', **context)


@app.route('/create', methods=['POST'])
def create():
    """
    Handles post from the "Add room" form on the homepage, and
    redirects to the new room.
    """
    name = request.form.get("name")
    if name:
        room, created = get_or_create(ChatRoom, name=name)
        return redirect(url_for('room', slug=room.slug))
    return redirect(url_for('rooms'))


class Estimator(object):

    def __init__(self):
        self.estimates = dict()

    def clear(self):
        self.estimates.clear()

    def add_estimate(self, estimator, estimate):
        self.estimates[estimator] = estimate

    def remove_estimate(self, estimator):
        if estimator in self.estimates:
            self.estimates.remove(estimator)

    def count(self):
        return len(self.estimates)

    def get_estimates(self):
        values = self.estimates.values()
        return {i: sum(1 for v in values if v == i) for i in set(values)}

class BroadcastRoomsMixin(RoomsMixin):
   
    def broadcast_to_room(self, room, event, *args):
        """This is sent to all in the room (in this particular Namespace)"""
        pkt = dict(type="event",
                   name=event,
                   args=args,
                   endpoint=self.ns_name)
        room_name = self._get_room_name(room)
        for sessid, socket in self.socket.server.sockets.iteritems():
            if 'rooms' not in socket.session:
                continue
            if room_name in socket.session['rooms']:
                socket.send_packet(pkt)


class ChatNamespace(BaseNamespace, BroadcastRoomsMixin, BroadcastMixin):
    room_nicknames = {}
    estimates = {}

    def initialize(self):
        self.logger = app.logger
        self.log("Socketio session started")

    def log(self, message):
        self.logger.info("[{0}] {1}".format(self.socket.sessid, message))

    def on_join(self, room):
        self.room = room
        self.join(room)
        self.log('joined room')
        return True

    def _room_estimates(self):
        result = self.estimates.get(self.room, None)
        if not result:
            result = self.estimates[self.room] = Estimator()
        return result

    def _room_nicknames(self):
        if not self.room:
            return None
        result = self.room_nicknames.get(self.room, None)
        if not result:
            result = self.room_nicknames[self.room] = []
        return result

    def on_nickname(self, nickname):
        if not self.room:
            self.log('room not set')
            return False, ''
        nicknames = self._room_nicknames()
        self.log('Nickname: {0}'.format(nickname))
        nicknames.append(nickname)
        self.log('Count: {0}'.format(len(nicknames)))
        self.session['nickname'] = nickname
        self.emit_to_room(self.room, 'announcement', '%s has connected' % nickname)
        self.broadcast_to_room(self.room, 'nicknames', nicknames)
        return True, nickname

    def recv_disconnect(self):
        # Remove nickname from the list.
        self.log('Disconnected')
        nickname = self.session.get('nickname', None)        
        if self.room and nickname:
            nicknames = self._room_nicknames()
            if nickname in nicknames:
                nicknames.remove(nickname)
            room_estimator = self._room_estimates()
            room_estimator.remove_estimate(nickname)
            self.emit_to_room(self.room, 'announcement', '%s has disconnected' % nickname)
            self.broadcast_to_room(self.room, 'nicknames', nicknames)        
            self.leave(self.room)
        self.disconnect(silent=True)
        return True

    def on_user_estimate(self, estimate):
        room_estimator = self._room_estimates()
        room_estimator.add_estimate(self.session['nickname'], estimate)
        self.log('User {0} estimated: {1}'.format(self.session['nickname'], estimate))
        self.log('estimates: {0}'.format(room_estimator.get_estimates()))
        if len(self._room_nicknames()) <= room_estimator.count():
            self.broadcast_to_room(self.room, 'estimate_to_room',
                room_estimator.get_estimates())
            room_estimator.clear()
        else:
            self.emit_to_room(self.room, 'estimate_submitted', self.session['nickname'])

    def on_clear_estimator(self):
        self._room_estimates().clear()
        self.broadcast_to_room(self.room, 'estimates_cleared', self.session['nickname'])
        return True

    

@app.route('/socket.io/<path:remaining>')
def socketio(remaining):
    try:
        socketio_manage(request.environ, {'/chat': ChatNamespace}, request)
    except:
        app.logger.error("Exception while handling socketio connection",
                         exc_info=True)
    return Response()


if __name__ == '__main__':
    app.run()
