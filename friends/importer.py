from django.conf import settings
from django.utils import simplejson as json

import re
from collections import defaultdict

try:
    import vobject
except ImportError:
    pass

try:
    import ybrowserauth
except ImportError:
    pass

from django.contrib.auth.models import User
from friends.models import Contact

EMAIL_REGEX = r".*?\b([A-Z0-9._%%+-]+@[A-Z0-9.-]+\.([A-Z]{2,4}|museum))\b.*"
EMAIL_REGEX_MATCH = r"^%s$" % EMAIL_REGEX

def get_oauth_var(service, variable_key, settings=settings.OAUTH_SETTINGS):
    """ Helper to return OAuth variables from settings file """
    try:
        return settings[service.upper()][variable_key.upper()]
    except KeyError:
        return None

def import_outlook(stream, user):
    import csv, tempfile
    """
    Imports the contents of an Outlook CSV file into the contacts of the given user
    
    Returns a tuple of (number imported, total number of records).
    """ 
    total = 0
    imported = 0
    Contact.objects.filter(owner=user, type='O', user__isnull=True).delete()
    # Fix lines that have breaks in them
    # Determine the delimiter
    csfile = None
    if len(stream) < 100:
        try:
            csfile = open(stream,'rU')
            stream = csfile.read(500)
            csfile.close()
            #print csfile.name
        except IOError, inst:
            #print "%s" % inst
            pass
    if not csfile:
        csfile = tempfile.NamedTemporaryFile()
        csfile.file.write(stream)
        csfile.file.close()
    csv_fields = stream[:500].split(",")
    tsv_fields = stream[:500].split("\t")
    if len(csv_fields) > len(tsv_fields):
        delim = ","
    else:
        delim = "\t"
    reader = csv.reader(open(csfile.name,'rU'),delimiter=delim)
    lines = [row for row in reader]
    fields = ('\t'.join(lines[0]).lower()).split('\t')
    #print fields
    field_lookups = {
        'email': ["email","e-mail","e-mail address","email address"],
        'first_name': ["first_name","first name","first","given name"],
        'last_name': ["last_name","last name","last","family name"],
        'name': ["name"],
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
                if len(c):
                    current_field = "%s_%s" % (c,field)
                else:
                    current_field = field
                #print "Current field is %s" % current_field
                try:
                    if len(c):
                        current_lookup = "%s %s" % (c,lookup)
                    else:
                        current_lookup = lookup
                    #print "Current lookup is %s" % current_lookup
                    match = fields.index(current_lookup)
                    if match > -1:
                        #print "Field %d is a match for %s" % (match, lookup)
                        field_indices[current_field].append(match)
                except ValueError:
                    pass
                for i in range(1,5):
                    try:
                        match = fields.index("%s %d" % (current_lookup,i))
                        field_indices[current_field.replace(' ','_')].append(match)
                    except ValueError:
                        pass
    if len(field_indices):
        # we are using the fields, so chop off the first line
        #print lines[0]
        lines = lines[1:]
        #print "Now the first line is \n%s" % lines[0]
    if not field_indices.has_key('email'):
        # Find out which fields contain an email address. That's all we're gathering.
        hold_email_fields=set()
        for l in lines[:10]:
            for f in range(0,len(l)):
                if re.match(EMAIL_REGEX_MATCH, l[f], re.IGNORECASE):
                    hold_email_fields.add(f)
        field_indices['email']=list(hold_email_fields)
    print field_indices
    if not (field_indices.has_key('email') and len(field_indices['email']) >= 1):
        return 0, 0
    for line in lines:
        if not re.search(EMAIL_REGEX," ".join(line), re.IGNORECASE):
            print "No email in this line: %s" % " ".join(line)
            continue
        if len(line):
            total += 1
            contact_vals = {}
            for col, col_indices in field_indices.items():
                for col_index in col_indices:
                    #print "Now looking at column %d in %s"  % (col_index, line)
                    if len(line[col_index].strip()):
                        if "street" in col:
                            if contact_vals.has_key(col):
                                contact_vals[col]="%s, %s" (contact_vals[col], line[col_index])
                        else:
                            contact_vals[col]=line[col_index]
                            break
            if not contact_vals.has_key('email'):
                if re.match(EMAIL_REGEX, (' ').join(line), re.IGNORECASE):
                    contact_vals['email'] = re.sub(EMAIL_REGEX, r"\1", (' ').join(line), re.IGNORECASE)
            for c in ["","work_","business_","home_"]:
                if contact_vals.has_key("%semail" % c):
                    email=contact_vals.pop("%semail" % c)
                    if not contact_vals.get('email',''):
                        contact_vals['email']=email
                if contact_vals.has_key("%sphone" % c):
                    phone=contact_vals.pop("%sphone" % c)
                    if not contact_vals.get('phone',''):
                        contact_vals['phone']=phone
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
            if contact_vals.has_key('email') and re.match(EMAIL_REGEX_MATCH,contact_vals['email'], re.IGNORECASE):
                print "Creating contact record with these values: %s" % contact_vals.items()
                _, created = create_contact_from_values(owner=user, type='O', **contact_vals)
                total += 1
                if created:
                    imported += 1
            else:
                print "Not importing, the values we got for this line were %s" % contact_vals.items()
    return imported, total
            

def import_vcards(stream, user):
    """
    Imports the given vcard stream into the contacts of the given user.
    
    Returns a tuple of (number imported, total number of cards).
    """
    
    Contact.objects.filter(owner=user, type='V', user__isnull=True).delete()
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

            contact, created = create_contact_from_values(owner=user, type='V', **contact_vals)
            if created:
                total += 1
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


def import_google(user):
    """
    Uses the given AuthSub token to retrieve Google Contacts and
    import the entries with an email address into the contacts of the
    given user.
    
    Returns a tuple of (number imported, total number of entries).
    """
    Contact.objects.filter(owner=user, type='G', user__isnull=True).delete()
    from gdata.contacts.service import ContactsService, ContactsQuery
    from gdata.auth import OAuthSignatureMethod, OAuthToken
    token_info = user.googletokens.all()[0]
    token = token_info.get_token()
    contacts_service = ContactsService(additional_headers={"GData-Version":"2"})
    contacts_service.SetOAuthInputParameters(OAuthSignatureMethod.HMAC_SHA1, 
            get_oauth_var('GOOGLE','OAUTH_CONSUMER_KEY'), 
            consumer_secret=get_oauth_var('GOOGLE','OAUTH_CONSUMER_SECRET'))
    contacts_service.SetOAuthToken(OAuthToken(key=token.token, secret=token.token_secret, oauth_input_params=contacts_service._oauth_input_params))
    entries = []
    groups = {}
    result = ""
    query = ContactsQuery(feed='/m8/feeds/groups/default/full')
    feed = contacts_service.GetGroupsFeed(query.ToUri())
    SYS_GROUP_REGEX=r"\s*system group:\s*"
    for entry in feed.entry:
        groups[re.sub(SYS_GROUP_REGEX,"",entry.title.text.lower())]=entry.id.text
    result+=("Groups: %s" % groups.items())
    for g in ["My Contacts","Friends","Coworkers"]:
#        result += "\n Looking at %s" % g
        if groups.has_key(g.lower()):
#            result += "\n Found %s" % g
            query = ContactsQuery()
            query.group=groups[g.lower()]
            feed = contacts_service.GetContactsFeed(query.ToUri())
            entries.extend(feed.entry)
            next_link = feed.GetNextLink()
            while next_link:
                feed = contacts_service.GetContactsFeed(uri=next_link.href)
                entries.extend(feed.entry)
                next_link = feed.GetNextLink()
    total = 0
    imported = 0
    imported_emails=[]
#    raise Exception(result)
    for entry in entries:
        total += 1
        contact_vals={}
        contact_vals['name'] = entry.title.text
        for e in entry.email:
            if e.primary:
                contact_vals['email'] = e.address
                break
            elif not contact_vals.has_key('email'):
                contact_vals['email'] = e.address
        if contact_vals.has_key('email') and contact_vals['email'] not in imported_emails:
            imported_emails.append(contact_vals['email'])
            _, created = create_contact_from_values(owner=user, type='G', **contact_vals)
            if created:
                imported += 1
    return imported, total

def create_contact_from_values(owner=None, type=None, **values):
    created = False
    email = values.get('email')
    if not email:
        return None, False
    try:
        contact = Contact.objects.get(owner=owner, email=email)
    except Contact.DoesNotExist:
        created = True
        contact = Contact(owner=owner, **values)
        try:
            contact.user = User.objects.get(email__iexact=email) 
        except User.DoesNotExist:
            pass
        if type:
            contact.type = type 
        contact.save()
    return contact, created