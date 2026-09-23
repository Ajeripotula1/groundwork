// Convert ISO datestring into data format based on users current location
export const formatDate = (iso) => new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(iso));
