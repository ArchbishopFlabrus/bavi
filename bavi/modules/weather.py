import datetime
import requests
import json
import urllib.parse as urlparse
import logging
import irc.strings

# Set up logging
log = logging.getLogger('bavi.modules.weather')

# Configs
w_api_key = '0e922ee41b5591219593936c8e92b62b'
w_api_version = '2.5'
w_proto = 'http://'
w_url_base = 'api.openweathermap.org/data/'
degree_sign = u'\N{DEGREE SIGN}'

valid_langs = [
    'ar', 'bg', 'ca', 'cz', 'de', 'el', 'en', 'fa', 'fi', 'fr', 'gl',
    'hr', 'hu', 'it', 'ja', 'kr', 'la', 'lt', 'mk', 'nl', 'pl', 'pt',
    'ro', 'ru', 'se', 'sk', 'sl', 'es', 'tr', 'ua', 'vi', 'zh_cn', 'zh_tw'
    ]


def init(bot):

    log.info('initializing the weather module')
    bot.add_command('weather', get_weather)
    bot.add_command('setweatherlocation', set_location)
    bot.add_command('setweatherunits', set_units)
    bot.add_command('setweatherlang', set_lang)

    c = bot.db.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS weather_info (
            nick TEXT,
            location TEXT,
            units TEXT,
            lang TEXT,
            created_at DATETIME,
            updated_at DATETIME,
            PRIMARY KEY (nick)
        )
    ''')


def get_weather(bot, source, target, message, **kwargs):
    '''
    .weather: retrieve the weather for a user or locale.

    Usage:
        .weather            Get the weather for your locale.
        .weather user       Get the weather for another user's locale.
        .weather 30303      Get the weather for zip code 30303, US.
        .weather Kalamazoo  Get the weather for Kalamzoo, MI
    '''

    nick = irc.strings.lower(source.nick)

    # If we have input...
    if len(message.strip()) > 0:

        arg = message.strip()

        if ',' in arg:
            # ',' is not a valid nickname character.
            # Assume we have a location.
            location = arg
        else:
            # Check if we have a nick on file.
            nick_check = get_location(bot, irc.strings.lower(arg))

            if nick_check == None:
                # No nick => assume input is a location.
                location = arg
            else:
                # If we got something back, use that.
                location = nick_check
    else:
        # Otherwise, assume the calling user's nick.
        arg = nick
        location = get_location(bot, arg)

    # Check the location for a failure condition
    if location is None:
        bot.reply_to(
            source,
            target,
            'I don\'t know the location for ' + arg
        )
        return

    # Assemble the URL.
    url = w_proto + w_url_base + w_api_version + '/weather?'

    # Assemble parameters for the query string.
    # type:like uses closest result.
    # Always use the lang and units for the calling user, if available.
    gets = {
        'q': location,
        'type': 'like',
        'units': get_units(bot, nick),
        'lang': get_lang(bot, nick),
        'appid': w_api_key
    }

    # Make the request
    response = requests.get(url + urlparse.urlencode(gets))

    # Text output is json string, so load that.
    r = json.loads(response.text)

    # Ensure a valid response.
    if r['cod'] != 200:
        bot.reply_to(
            source,
            target,
            'HTTP ' + r['cod'] + ':' + r['message'] + ' received from API.'
        )
        return

    # Sanely express units for temp/wind.
    if gets['units'] == 'metric':
        degreesf = 'C'
        speedf = 'm/s'
    else:
        degreesf = 'F'
        speedf = 'mph'

    # Cobble together a string.
    weather_out = 'Weather for {0}, {1}: {2}, {3} (Min: {4}, Max: {5}), {6}% humidity, {7} wind.'.format(
        r['name'],
        r['sys']['country'],
        r['weather'][0]['description'],
        str(r['main']['temp']) + degree_sign + degreesf,
        str(r['main']['temp_min']),
        str(r['main']['temp_max']),
        str(r['main']['humidity']),
        str(r['wind']['speed']) + speedf
        )

    '''
    weather_out = "Weather for " + r['name'] + ", " + r['sys']['country']
    + ": " + r['weather'][0]['description'] + ", "
    + str(r['main']['temp']) + degree_sign + degreesf + " "
    + "(Min: " + str(r['main']['temp_min']) + " - "
    + "Max: " + str(r['main']['temp_max']) + "), "
    + str(r['main']['humidity']) + "% humidity, "
    + str(r['wind']['speed']) + speedf + " wind."
    '''

    # Finally, send the reply.
    bot.reply_to(source, target, weather_out)


def set_location(bot, source, target, message, **kwargs):
    '''
    .setweatherlocation: Set your location for usage with .weather

    Usage:
        .setweatherlocation 30303    Set your location to 30303, US
        .setweatherlocation Helsinki Set your location to Helsinki, Finland
    '''

    location = message.strip()
    nick = irc.strings.lower(source.nick)

    # Ensure we have some kind of input.
    if len(location) == 0:

        # Give them an example if they provide no input.
        bot.reply_to(
            source,
            target,
            'Please provide a location, for example: "Atlanta"'
        )

        return

    c = bot.db.cursor()
    now = datetime.datetime.now()

    # Update user's info
    c.execute('''
        UPDATE  weather_info
        SET     location = ?,
                updated_at = ?
        WHERE   nick = ?

    ''', (location, now, nick))

    bot.db.commit()

    # If we didn't have a row to update,
    # insert one instead.
    if c.rowcount == 0:
        c.execute('''
            INSERT INTO weather_info
            VALUES      (?, ?, ?, ?, ?, ?)
        ''', (nick, location, 'metric', 'en', now, now))

    bot.db.commit()

    # Inform the user.
    bot.reply_to(
        source,
        target,
        'Your weather locale has been set to {}'.format(location)
    )


def get_location(bot, arg):

    c = bot.db.cursor()
    c.execute('''
        SELECT location
        FROM   weather_info
        WHERE  nick = ?
    ''', (arg,))

    results = [location for location, in c]

    if len(results) == 0:
        return None
    else:
        return results[0]


def set_units(bot, source, target, message, **kwargs):
    '''
    .setweatherunits: Set your preferred units for .weather

    Usage:
        .setweatherunits [metric,imperial]    Default: metric
    '''
    # API requires either metric or imperial units.
    if message not in ['metric', 'imperial']:
        bot.reply_to(source, target, 'Invalid unit type.')
        return

    c = bot.db.cursor()
    c.execute('''
        UPDATE weather_info
        SET    units = ?,
               updated_at = ?
        WHERE  nick = ?
    ''', (message, datetime.datetime.now(), irc.strings.lower(source.nick)))

    bot.db.commit()

    # If update query fails, notify the user.
    if c.rowcount == 0:
        bot.reply_to(source, target, 'Set location before choosing units!')
        return


def get_units(bot, arg):

    # If given a nick, check for the user's unit pref.
    c = bot.db.cursor()
    c.execute('''
        SELECT units
        FROM   weather_info
        WHERE  nick = ?
    ''', (arg,))

    results = [units for units, in c]

    # Default to metric units, because science.
    if len(results) == 0:
        return 'metric'
    else:
        return results[0]


def set_lang(bot, source, target, message, **kwargs):
    '''
    .setweatherlang: Set your preferred language for .weather

    Usage:
        .setweatherlang fi    Default: en
    '''
    # Check against define list of supported languages.
    if message not in valid_langs:
        bot.reply_to(
            source,
            target,
            'Unsupported language. See API doc for details. ' +
            'http://openweathermap.org/current#multi'
        )
        return

    c = bot.db.cursor()
    c.execute('''
        UPDATE weather_info
        SET    lang = ?,
               updated_at = ?
        WHERE  nick = ?
    ''', (message, datetime.datetime.now(), irc.strings.lower(source.nick)))

    bot.db.commit()

    # If update query fails, notify the user.
    if c.rowcount == 0:
        bot.reply_to(
            source,
            target,
            'Set location before choosing language!'
        )
        return


def get_lang(bot, arg):

    # If given a nick, check for the user's unit pref.
    c = bot.db.cursor()
    c.execute('''
        SELECT lang
        FROM   weather_info
        WHERE  nick = ?
    ''', (arg,))

    results = [lang for lang, in c]

    # Default to English.
    if len(results) == 0:
        return 'en'
    else:
        return results[0]
