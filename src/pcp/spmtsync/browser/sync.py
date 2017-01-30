from zope.interface import alsoProvides
from zope.component import getUtility

import plone.api

from plone.registry.interfaces import IRegistry
from plone.protect.interfaces import IDisableCSRFProtection

from Products.Five.browser import BrowserView
from Products.PlonePAS.utils import cleanId
from Products.CMFCore.utils import getToolByName

from pcp.spmtsync.browser import utils
from pcp.spmtsync.browser import config


logger = utils.getLogger('var/log/spmtsync.log')


def preparedata(values, site, additional_org, email2puid, logger):

    logger.debug(values)

    fields = values.copy()

    title = fields['name'].encode('utf8')
    scl = fields['service_complete_link']['related']['href']
    identifiers = [{'type': 'spmt_uid',
                    'value': fields['uuid']},
                   ]

    fields['title'] = title
    fields['description'] = fields['description_external']
    if 'localhost' in scl:
        registry = getUtility(IRegistry)
        SPMT_BASE = registry['pcp.spmtsync.baseurl']
        scl = scl.replace('localhost', SPMT_BASE)
    fields['service_complete_link'] = scl
    fields['identifiers'] = identifiers
    # link contacts
    contact_info = fields['contact_information']
    if contact_info is not None:
        contact_url = fields['contact_information']['links']['self']
        # first map exceptions
        contact_data = utils.getDataFromSPMT(contact_url)
        contact_email = contact_data['external_contact_information']['email']
        email = config.creg2dp_email.get(contact_email, contact_email)
        # then look up corresponding UID
        contact_uid = email2puid.get(email, None)
        if contact_uid is None:
            logger.warning("'%s' not found - no contact set for '%s'"
                           % (contact_email, title))
        else:
            fields['contact'] = contact_uid
    # same for the service owner
    owner_email = fields['service_owner']['email']
    o_email = config.creg2dp_email.get(owner_email, owner_email)
    owner_uid = email2puid.get(o_email, None)
    if owner_uid is None:
        logger.warning("'%s' not found - no service owner set for '%s'"
                       % (owner_email, title))
    else:
        fields['service_owner'] = owner_uid

    return fields.copy()


def flattenlinks(data):
    """Unpack and inline the embedded links"""
    for field in config.link_fields:
        link = data[field]['related']['href']
        data[field] = link
    details_link = data['links']['self']
    data['links'] = details_link
    return data


def resolveDependencies(site, data):
    """Resolve dependencies by looking up the UIDs of the respective
    services. It is assumed that the services are there and can be
    looked up by name in the 'catalog' folder."""
    deps = data['dependencies_list']['services']
    if not deps:
        data['dependencies'] = []
    else:
        dependencies = []
        for dep in deps:
            name = dep['service']['name']
            uid = site['catalog'][cleanId(name)].UID()
            dependencies.append(uid)
        data['dependencies'] = dependencies
    return data


def update_object(obj, data):
    """ Update `obj` with data dict using Archetypes edit() method.
        We preserve the original `data` dictionary in order to check
        during later updates for changed data in order to avoid
        unneccessary copy of the same object in portal_repository.
    """

    portal_repo = plone.api.portal.get_tool('portal_repository')
    last_saved_data = getattr(obj, '_last_saved_data', None)
    if last_saved_data != data:
        obj.edit(**data)
        obj.reindexObject()
        obj._last_saved_data = data
        portal_repo.save(obj=obj, comment='Synchronization from SPMT')
        logger.info(
            "Updated {}/{} in the 'catalog' folder".format(obj.portal_type, obj.getId()))
    else:
        logger.debug('Up2date {}/{}'.format(obj.portal_type, obj.getId()))


def check_and_create_object(container, portal_type, obj_id):
    """ Check if `container` contains an object with ID `obj_id`.
        If not, create it and return it.
    """
    if obj_id not in container.objectIds():
        obj = plone.api.content.create(
            type=portal_type,
            container=container,
            id=obj_id)
        logger.info('Adding {}/{} to "{}/{}/{}"'.format(portal_type, obj_id, container.portal_type, container.absolute_url(1), container.Title()))

    obj = container[obj_id]
    if plone.api.content.get_state(obj) != 'internal':
        plone.api.content.transition(obj=obj, to_state='internal')
        obj.reindexObject()
    return obj

def addImplementationDetails(site, impl, data, logger):
    """Adding implementation details to a service component implementation"""
    logger.debug("addImplemenationDetails called with this data: '%s'" % data)
    id = cleanId('version-' + data['version'])
    details = check_and_create_object(impl, 'ServiceComponentImplementationDetails', id)

    data['title'] = 'Version ' + data['version']
    data['description'] = 'Implementation details of ' + \
        impl.Title() + ': version ' + data['version']
    data['identifiers'] = [{'type': 'spmt_uid',
                            'value': data['uuid']},
                           ]
    raw_config_data = data['configuration_parameters']
    if raw_config_data is not None:
        config_items = raw_config_data.splitlines()
        keys = [item.split()[0] for item in config_items]
        data['configuration_parameters'] = keys
    else:
        data['configuration_parameters'] = []

    update_object(details, data)


def addImplementation(site, component, data, logger):
    """Adding an implementation to a service component"""
    logger.debug("addImplemenation called with this data: '%s'" % data)
    id = cleanId(data['name'])
    implementation = check_and_create_object(component, 'ServiceComponentImplementation', id)

    data['title'] = component.Title() + ' implementation: ' + data['name']
    data['identifiers'] = [{'type': 'spmt_uid',
                            'value': data['uuid']},
                           ]

    update_object(implementation, data)

    details_data = utils.getDataFromSPMT(
        data['component_implementation_details_link']['related']['href'])
    details = details_data['service_component_implementation_details_list'][
        'service_component_implementation_details']
    if not details:
        logger.info("No implemenation details found for '%s'" % data['title'])
        return
    for detail in details:
        addImplementationDetails(site, implementation, detail, logger)


def addComponent(service, site, data, logger):
    """Adding a service component to 'service' described by 'data'"""
    logger.debug("addComponent called with this data: '%s'" % data)
    id = cleanId(data['name'])
    component = check_and_create_object(service, 'ServiceComponent', id)

    data['title'] = "Service component '%s'" % data['name']
    data['identifiers'] = [{'type': 'spmt_uid',
                            'value': data['uuid']},
                           ]

    update_object(component, data)

    implementations_data = utils.getDataFromSPMT(
        data['service_component_implementations_link']['related']['href'])
    # print implementations_data
    implementations = implementations_data[
        'service_component_implementations_list']['service_component_implementations']
    if not implementations:
        logger.info("No implemenations found for '%s'" % data['title'])
        return
    for implementation in implementations:
        addImplementation(site, component, implementation, logger)


def addDetails(site, parent, data, logger):
    """Adding service details"""

    details = check_and_create_object(parent, 'Service Details', 'details')

    data['title'] = 'Service Details'
    data['description'] = 'Details of the %s service' % parent.Title()
    data = flattenlinks(data)
    data = resolveDependencies(site, data)
    data['identifiers'] = [{'type': 'spmt_uid',
                            'value': data['uuid']},
                           ]

    update_object(details, data)

    # adding service components if any
    full_data = utils.getDataFromSPMT(data['links'])
    scl = full_data.get('service_components_list', None)
    if scl is None:
        logger.debug('No service components found for %s' % parent.Title())
        return None
    for sc in scl['service_components']:
        addComponent(parent, site, sc['component'], logger)


class SPMTSyncView(BrowserView):
    """Enable import of services from SPMT"""

    def sync(self, force=False):
        """
        Main method to be called to sync content from SPMT
        """

        alsoProvides(self.request, IDisableCSRFProtection)

        site = plone.api.portal.get()
        target_folder = self.context
        spmt_services = utils.getServiceData()
        email2puid = utils.email2puid(site)

        logger.debug("Iterating over the service data")

        existing_services = set(target_folder.objectIds())
        current_spmt_services = set()

        for entry in spmt_services:
            shortname = entry['name']
            id = cleanId(shortname)
            if id == 'test':
                continue
            if id is None:
                logger.warning("Couldn't generate id for ", values)
                continue

            current_spmt_services.add(id)

            service = check_and_create_object(target_folder, 'Service', id)

            # retrieve data to extended rather than overwrite
            additional = service.getAdditional()
            data = preparedata(entry, site, additional, email2puid, logger)
            update_object(service, data)

        # handle removed services: back to private state
        removed_services = existing_services - current_spmt_services
        for id in removed_services:
            service = target_folder[id]
            if plone.api.content.get_state(service) != 'private':
                plone.api.content.transition(obj=service, to_state='private')

        # second loop so dependencies in 'details' can be resolved
        for entry in spmt_services:
            shortname = entry['name']
            id = cleanId(shortname)
            if id == 'test':
                continue
            try:
                service = target_folder[id]
                data = entry['service_details_list']['service_details'][0]
                # we assume there is at most one
                addDetails(site, service, data, logger)
            except IndexError:
                pass

        return 'DONE'
