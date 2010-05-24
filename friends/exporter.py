import vobject

def export_vcards(contacts):
    result = []
    for contact in contacts:
        card = vobject.vCard()
        card.add('n')
        card.n.value = vobject.vcard.Name( family=contact.last_name, given=contact.first_name )
        card.add('fn')
        card.fn.value = contact.get_full_name()
        card.add('email')
        card.email.value = contact.email
        card.email.type_param = 'INTERNET'
        for phone in ["phone","mobile"]:
            try:
                tel = getattr(contact,phone)
                card.add('tel')
                card.tel.value = tel
            except AttributeError:
                pass
        result.append(card.serialize())
    return "\n".join(result)
