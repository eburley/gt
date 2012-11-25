$(function() {

    var WEB_SOCKET_SWF_LOCATION = '/static/js/socketio/WebSocketMain.swf',
        socket = io.connect('/chat');

    socket.on('connect', function () {
        $('#chat').addClass('connected');
        socket.emit('join', window.room);
    });

    socket.on('announcement', function (msg) {
        $('#lines').append($('<p>').append($('<em>').text(msg)));
    });

    socket.on('nicknames', function (nicknames) {
        $('#nicknames').empty().append($('<span>Online: </span>'));
        for (var i in nicknames) {
          $('#nicknames').append($('<b>').text(nicknames[i]).attr('data-nick',nicknames[i]));
        }
        apply_estimate_state();
    });

    socket.on('msg_to_room', message);


    var estimate_state = {};
    function apply_estimate_state(){
        $('#nicknames b[data-nick]').removeClass('estimated');
        $.each(estimate_state, function(key,val){
            $('#nicknames b[data-nick="' + key + '"]').toggleClass('estimated',val);
        });
    }

    socket.on('estimate_submitted',function(who) {
       //$('#lines').append($('<p>').append($('<em>').text(who + ' submitted estimate')));
       estimate_state[who] = true;
       apply_estimate_state();
    });

    socket.on('estimate_to_room', function(estimates) {
        
        var results = null, tmp = null,
            keys = Object.keys(estimates).sort(),
            min = 1000, max = 0;

        if (keys.length === 1) {
            results = $('<p class="consensus">').append($('<span>').text(estimates[keys[0]]));
        }
        else {
            results = $('<p class="disagreement">');

            // figure out outliers, mehs, and populars            
            $.each(keys, function(idx,val) {
                min = Math.min(min,estimates[val]);
                max = Math.max(max,estimates[val]);
            });
        
            // build the nodes.
            $.each(keys, function(idx,val) {
                tmp = $('<span>').text(val);

                var count = estimates[val];
                var apply_class = 'meh';
                if ( min !== max ) {
                    if (count === max) {
                        apply_class = 'popular';
                    }
                    else if (count === min) {
                        apply_class = 'outlier';
                    }
                }
                tmp.addClass(apply_class);

                results.append(tmp);
            });
        }
        results.append($('<div style="clear:both">'));

       $('#lines').append(results);
       clear();
    });

    socket.on('estimates_cleared', function (who) {
        message(who,'cleared estimates');
        clear();
    });

    socket.on('reconnect', function () {
        $('#lines').remove();
        message('System', 'Reconnected to the server');
    });

    socket.on('reconnecting', function () {
        message('System', 'Attempting to re-connect to the server');
    });

    socket.on('error', function (e) {
        message('System', e ? e : 'A unknown error occurred');
    });

    function message (from, msg) {
        $('#lines').append($('<p>').append($('<b>').text(from), msg));
    }

    function clear () {
        $('#numbers button[data-value]').removeClass('pressed');
        estimate_state = {};
        apply_estimate_state();
    }

    // DOM manipulation
    $(function () {
        $('#set-nickname').submit(function (ev) {
            socket.emit('nickname', $('#nick').val(), function (set) {
                if (set) {
                    clear();
                    return $('#chat').addClass('nickname-set');
                }
                $('#nickname-err').css('visibility', 'visible');
            });
            return false;
        });

        $('#numbers button[data-value]').click(function (ev){
            socket.emit('user estimate', $(this).attr('data-value'));
            $(this).addClass('pressed');
            estimate_state[$('#nick').val()] = true;
            apply_estimate_state();
            return false;
        });

        $('#reset_estimates').click(function(ev) {
            socket.emit('clear estimator');
            return false;
        });

    });

});