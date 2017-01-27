# pcp.spmtsync
Plone/DPMT add-on providing functionality to import and update content from EUDAT's Service Portfolio Management Tool (SPMT)

There is only one browser view available through this package called `sync`. Invoking it via URL pulls in all content from EUDAT's [service portfolio.] (https://sp.eudat.eu)

To make it available on a folder one needs to manually assign the marker interface `pcp.spmtsync.IPortfolioRoot` to a folder where the `Service` type from [pcp.contenttypes] (https://github.com/EUDAT-DPMT/pcp.contenttypes) can be added.
