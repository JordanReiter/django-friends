from django.conf import settings
from django.utils import simplejson as json

import re
from collections import defaultdict

try:
    import gdata.contacts.service
except ImportError:
    pass

try:
    import vobject
except ImportError:
    pass

try:
    import ybrowserauth
except ImportError:
    pass

from friends.models import Contact

EMAIL_REGEX = r"^.*?\b([A-Z0-9._%%+-]+@[A-Z0-9.-]+\.([A-Z]{2,4}|museum))\b.*$"

def import_outlook(stream, user):
    import csv, tempfile
    """
    Imports the contents of an Outlook CSV file into the contacts of the given user
    
    Returns a tuple of (number imported, total number of records).
    """ 
    total = 0
    imported = 0
    # Fix lines that have breaks in them
    # Determine the delimiter
    csv_fields = stream[:500].split(",")
    tsv_fields = stream[:500].split("\t")
    if len(csv_fields) > len(tsv_fields):
        delim = ","
    else:
        delim = "\t"
    csfile = tempfile.NamedTemporaryFile()
    csfile.file.write(stream)
    csfile.file.close()
    reader = csv.reader(open(csfile.name,'rU'),delimiter=delim)
    lines = [row for row in reader]
    field_lookups = {
        'email': ["email","e-mail","e-mail address","email address"],
        'first_name': ["first_name","first name","first"],
        'last_name': ["last_name","last name","last"],
        'address': ['address'],
        'street': ['street address','street','street_address'],
        'city': ['city'],
        'state': ['state','province'],
        'zip': ['zip','zip code','zipcode','postal code','postal_code'],
        'country': ['country'],
        'phone':['phone','phone number'],
        'fax':['fax','fax number'],
        'mobile':['mobile','mobile phone'],
        'website':['web page','url','website','home page','homepage']
    }
    field_indices = defaultdict(list)
    for field, lookups in field_lookups.items():
        current_field = field
        for lookup in lookups:
            for c in ["","work","business","home"]:
                print "%d: %s, %s, %s" % ( (time.time()-start), field, lookup, c)
                if len(c):
                    current_field = "%s_%s" % (c,field)
                else:
                    current_field = field
                try:
                    if len(c):
                        current_lookup = "%s %s" % (c,lookup)
                    else:
                        current_lookup = lookup
                    #print "Trying to find %s in %s" % (lookup, fields)
                    match = fields.index(current_lookup)
                    if match > -1:
                        field_indices[current_field].append(match)
                except ValueError:
                    pass
                for i in range(1,5):
                    try:
                        match = fields.index("%s %d" % (lookup,i))
                        field_indices[current_field.replace(' ','_')].append(match)
                    except ValueError:
                        pass
    if len(field_indices) and field_indices.has_key('email'):
        # we are using the fields, so chop off the first line
        lines = lines[1:]
    else:
        # Find out which fields contain an email address. That's all we're gathering.
        for f in range(0,len(lines[0])):
            if re.match(EMAIL_REGEX, field[f], re.IGNORECASE):
                field_indices['email'].append(f)
    for line in lines:
        if len(line):
            total += 1
            print "\n\n\n\nLooking at line %s\n\n" % line
            contact_vals = {}
            for col, col_indices in field_indices.items():
                for col_index in col_indices:
                    if len(line[col_index].strip()):
                        if "street" in col:
                            if contact_vals.has_key(col):
                                contact_vals[col]="%s, %s" (contact_vals[col], vals[col_index])
                        else:
                            contact_vals[col]=vals[col_index]
                            break
            if not contact_vals.has_key('email'):
                if re.match(EMAIL_REGEX, (' ').join(line), re.IGNORECASE):
                    contact_vals['email'] = re.sub(EMAIL_REGEX, r"\1", (' ').join(line), re.IGNORECASE)
            for c in ["","work_","business_","home_"]:
                if contact_vals.has_key("%semail" % c):
                    email=contact_vals.pop("%semail" % c)
                    if not contact_vals.get('email',''):
                        contact_vals['email']=email
                if contact_vals.has_key("%saddress" % c):
                    addr=contact_vals.pop("%saddress" % c)
                    if not contact_vals.get('address',''):
                        contact_vals['address']=addr
                street = contact_vals.pop(('%sstreet' % c),None)
                city = contact_vals.pop(('%scity' % c),None)
                state = contact_vals.pop(('%sstate' % c),None)
                zip = contact_vals.pop(('%szip' % c),None)
                if (street or city or state) and not contact_vals.has_key('address'):
                    address = ""
                    if street:
                        address += street
                    if city:
                        if len(address):
                            address += ", "
                        address += city
                    if state:
                        if len(address):
                            address += ", "
                        address += state
                    if zip and len(address):
                        address += " " + zip
                    contact_vals['address']=address
            if not contact_vals.get('Name',None):
                contact_vals['name']=("%s %s" % (contact_vals.get('first_name',''), contact_vals.get('last_name',''))).strip()
            try:
                Contact.objects.get(owner=user, email=contact_vals['email'])
            except Contact.DoesNotExist:
                Contact(owner=user,type='I',**contact_vals).save()
                imported += 1
            except KeyError:
                raise Exception("Email not found; this is the line:\n%s\n" % vals)
    return imported, total
            

def import_vcards(stream, user):
    """
    Imports the given vcard stream into the contacts of the given user.
    
    Returns a tuple of (number imported, total number of cards).
    """
    
    total = 0
    imported = 0
    for card in vobject.readComponents(stream):
        total += 1
        contact_vals = {}
        try:
            contact_vals['name'] = card.fn.value
            contact_vals['email'] = card.email.value
            try:
                name_field = card.contents.get('n')
                try:
                    contact_vals['last_name'] = name_field[0].value.family.strip()
                    contact_vals['first_name'] = name_field[0].value.given.strip()
                except:
                    pass
            except:
                pass

            try:
                for tel in card.contents.get('tel'):
                    try:
                        type = tel.params
                    except AttributeError:
                        type = []
                    for t in type:
                        if t == 'CELL' or t == 'MOBILE':
                            contact_vals['mobile'] = tel.value
                            break
                        if t == 'FAX':
                            contact_vals['fax'] = tel.value
                            break
                        else:
                            if not contact_vals.has_key('phone') or t == 'pref': 
                                contact_vals['phone'] = t.value
                                break
            except:
                pass

            try:
                Contact.objects.get(owner=user, email=email)
            except Contact.DoesNotExist:
                Contact(owner=user, type='V', **contact_vals).save()
                imported += 1
        except AttributeError:
            pass # missing value so don't add anything
    return imported, total


def import_yahoo(bbauth_token, user):
    """
    Uses the given BBAuth token to retrieve a Yahoo Address Book and
    import the entries with an email address into the contacts of the
    given user.
    
    Returns a tuple of (number imported, total number of entries).
    """
    
    ybbauth = ybrowserauth.YBrowserAuth(settings.BBAUTH_APP_ID, settings.BBAUTH_SHARED_SECRET)
    ybbauth.token = bbauth_token
    address_book_json = ybbauth.makeAuthWSgetCall("http://address.yahooapis.com/v1/searchContacts?format=json&email.present=1&fields=name,email")
    address_book = json.loads(address_book_json)
    
    total = 0
    imported = 0
    
    for contact in address_book["contacts"]:
        total += 1
        email = contact['fields'][0]['data']
        try:
            first_name = contact['fields'][1]['first']
        except (KeyError, IndexError):
            first_name = None
        try:
            last_name = contact['fields'][1]['last']
        except (KeyError, IndexError):
            last_name = None
        if first_name and last_name:
            name = first_name + " " + last_name
        elif first_name:
            name = first_name
        elif last_name:
            name = last_name
        else:
            name = None
        try:
            Contact.objects.get(user=user, email=email)
        except Contact.DoesNotExist:
            Contact(user=user, name=name, email=email, first_name=first_name, last_name=last_name).save()
            imported += 1
    
    return imported, total


def import_google(authsub_token, user):
    """
    Uses the given AuthSub token to retrieve Google Contacts and
    import the entries with an email address into the contacts of the
    given user.
    
    Returns a tuple of (number imported, total number of entries).
    """
    
    contacts_service = gdata.contacts.service.ContactsService()
    contacts_service.auth_token = authsub_token
    contacts_service.UpgradeToSessionToken()
    entries = []
    feed = contacts_service.GetContactsFeed()
    entries.extend(feed.entry)
    next_link = feed.GetNextLink()
    while next_link:
        feed = contacts_service.GetContactsFeed(uri=next_link.href)
        entries.extend(feed.entry)
        next_link = feed.GetNextLink()
    total = 0
    imported = 0
    for entry in entries:
        name = entry.title.text
        for e in entry.email:
            email = e.address
            total += 1
            try:
                Contact.objects.get(user=user, email=email)
            except Contact.DoesNotExist:
                Contact(user=user, name=name, email=email).save()
                imported += 1
    return imported, total
